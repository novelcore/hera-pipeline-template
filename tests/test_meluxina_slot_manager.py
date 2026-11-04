"""PRD-HPC-1609 F-03: the slot manager — a MeluXina job with node sharing on hosts up to
three waiting jobs of its own scope on its node's free GPUs, one Slurm job step each.

The real slot manager program runs as a process against a fake Slurm (fakeslurm.py)
that behaves like MeluXina's where it matters. Steps are real processes, so the clean
step environment, the /proc memory watchdog, stop and TERM are exercised for real.
Run:  python -m pytest tests/ -v
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kaos_pipeline.meluxina import MELUXINA_SUBMIT_CODE  # noqa: E402

SCOPE = "a1b2c3d4e5"
HEADER = "#!/bin/bash -l\n# kaos-job v2 scope=%s\nset +e\n" % SCOPE


def _slots_code():
    g = {}
    exec(MELUXINA_SUBMIT_CODE.split("API = ")[0], g)
    return g["SLOTS"]


def _job(name, script_body, state="PENDING", comment="", limit="10:00", header=HEADER):
    return {"name": name, "state": state, "reason": "Priority", "partition": "gpu", "limit": limit,
            "comment": comment, "script": header + script_body, "held": False}


class Node:
    """One MeluXina node with a fake Slurm and the slot manager as host job 100."""

    def __init__(self, tmp_path, guests, own_body="echo own $KAOS_JOB_ID $CUDA_VISIBLE_DEVICES > $OUT/own\nexit 0\n",
                 mem_mb=491520, extra_env=None):
        self.tmp = tmp_path
        self.out = tmp_path / "out"
        self.out.mkdir()
        (tmp_path / "home").mkdir()
        bindir = tmp_path / "bin"
        bindir.mkdir()
        for tool in ("squeue", "scontrol", "srun", "scancel"):
            (bindir / tool).symlink_to(ROOT / "tests" / "fakeslurm.py")
        (ROOT / "tests" / "fakeslurm.py").chmod(0o755)
        jobs = {"100": _job("kaos-%s-wfhost-train" % SCOPE, own_body, state="RUNNING", comment="kaos-commit=aaaaaaa1")}
        # A real host ends at its own time limit: one hour from now.
        jobs["100"]["end"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 3600))
        jobs.update(guests)
        for j in jobs.values():   # like the runner's scripts: every input is exported in the script
            head, sep, rest = j["script"].partition("set +e\n")
            j["script"] = head + sep + "export OUT=%s\n" % self.out + rest if sep else j["script"]
        self.state = tmp_path / "slurm.json"
        self.state.write_text(json.dumps({"jobs": jobs}))
        own = tmp_path / "own.sh"
        own.write_text(jobs["100"]["script"])
        slots = tmp_path / "slots.py"
        slots.write_text(_slots_code())
        self.env = {"PATH": str(bindir) + os.pathsep + os.environ["PATH"], "HOME": str(tmp_path / "home"),
                    "USER": "u104378", "LANG": "C.UTF-8", "FAKE_SLURM_STATE": str(self.state),
                    "SLURM_JOB_ID": "100", "SLURM_CPUS_ON_NODE": "128", "SLURM_MEM_PER_NODE": str(mem_mb),
                    "HPC_GPUS": "4", "KAOS_SCOPE": SCOPE, "KAOS_SCR": str(tmp_path / "scratch"),
                    "KAOS_IDLE_S": "1", "KAOS_POLL_S": "0.2", "OUT": str(self.out),
                    "HOST_SECRET": "the host's own token", "SLURM_EXPORT_ENV": "NONE", **(extra_env or {})}
        self.log = tmp_path / "host.log"
        self.proc = subprocess.Popen([sys.executable, str(slots), str(own)], env=self.env,
                                     stdout=open(self.log, "w"), stderr=subprocess.STDOUT)

    def jobs(self):
        return json.loads(self.state.read_text())["jobs"]

    def wait_for(self, cond, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if cond(self.jobs()):
                    return True
            except (ValueError, KeyError):
                pass
            time.sleep(0.1)
        return False

    def finish(self, timeout=60):
        try:
            rc = self.proc.wait(timeout=timeout)
        finally:
            # On MeluXina Slurm ends a finished host's steps; here the test does.
            for step in json.loads(self.state.read_text()).get("steps", {}).values():
                try:
                    os.killpg(step["pid"], signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        return rc, self.log.read_text()


def test_a_host_runs_waiting_jobs_of_its_scope_and_reports_each(tmp_path):
    guests = {
        "101": _job("kaos-%s-wf1-train" % SCOPE, "echo $KAOS_JOB_ID $CUDA_VISIBLE_DEVICES ${HOST_SECRET-unset} > $OUT/101\nsleep 1\nexit 0\n",
                    comment="kaos-commit=bbbbbbb2"),
        "102": _job("kaos-%s-wf2-train" % SCOPE,
                    'scontrol update JobId=$KAOS_JOB_ID "Comment=kaos-commit=bbbbbbb3 err3:boom|"\nexit 3\n',
                    comment="kaos-commit=bbbbbbb3"),
        "103": _job("kaos-otherscope1-wf3-train", "echo NO > $OUT/103\n", comment="kaos-commit=ccccccc4"),
        "104": _job("kaos-%s-wf4-train" % SCOPE, "echo NO > $OUT/104\n", header="#!/bin/bash -l\nset +e\n"),
        "105": _job("kaos-%s-wf5-train" % SCOPE, "echo NO > $OUT/105\n", limit="9-00:00:00"),
    }
    node = Node(tmp_path, guests)
    rc, log = node.finish()
    assert rc == 0, log
    jobs = node.jobs()

    # Taken, run on its own GPU with its own job id and no host inputs, reported, cancelled.
    job_id, gpu, secret = (node.out / "101").read_text().split()
    own_gpu = (node.out / "own").read_text().split()[2]
    assert job_id == "101" and gpu != own_gpu, "its own job id, its own GPU"
    assert secret == "unset", "a guest never sees the host's inputs"
    assert jobs["101"]["state"] == "CANCELLED"
    assert jobs["101"]["comment"] == "kaos-commit=bbbbbbb2 kaos-state=done rc=0 host=100"
    # A failing guest: its rc, its own error tail and its lease are all kept.
    assert jobs["102"]["comment"] == "kaos-commit=bbbbbbb3 kaos-state=done rc=3 host=100 err3:boom|"
    # The host's own step: its result in its own comment, lease first.
    assert jobs["100"]["comment"] == "kaos-commit=aaaaaaa1 kaos-state=done rc=0"
    assert (node.out / "own").read_text().split()[:2] == ["own", "100"]
    # Never touched: another scope, a v1 script, a job that does not fit the host's time.
    for jid in ("103", "104", "105"):
        assert jobs[jid]["state"] == "PENDING" and not jobs[jid]["held"], (jid, jobs[jid], log)
        assert not (node.out / jid).exists(), jid
    assert jobs["103"]["comment"] == "kaos-commit=ccccccc4"
    calls = json.loads(node.state.read_text())["calls"]
    assert not [c for c in calls if c[:2] in (["scontrol", "hold"], ["scontrol", "release"]) and c[2] in ("103", "105")]
    # The v1 job was only read (its script), never locked or held.
    assert not [c for c in calls if c[:2] in (["scontrol", "hold"], ["scontrol", "release"]) and c[2] == "104"]
    assert not list((tmp_path / "scratch" / "kaos-claims").glob("104-*"))
    # Done jobs leave no lock behind.
    assert not list((tmp_path / "scratch" / "kaos-claims").glob("10[12]-*"))
    assert (tmp_path / "home" / "slurm-101.out").exists(), "each guest logs to its own job's output file"


def test_stopping_a_guests_run_stops_only_its_step(tmp_path):
    guests = {"101": _job("kaos-%s-wf1-train" % SCOPE, "sleep 60\n", comment="kaos-commit=bbbbbbb2")}
    node = Node(tmp_path, guests, own_body="sleep 4\nexit 0\n")
    assert node.wait_for(lambda j: "kaos-state=taken" in j["101"]["comment"]), "guest never taken"
    t0 = time.time()

    def stop(st):  # the guest's waiter cancels its own job (a stopped run)
        st["jobs"]["101"]["state"] = "CANCELLED"
    data = json.loads(node.state.read_text())
    stop(data)
    node.state.write_text(json.dumps(data))
    rc, log = node.finish()
    assert rc == 0, log
    jobs = node.jobs()
    assert "kaos-state=done" not in jobs["101"]["comment"], "a stopped run gets no result"
    assert jobs["100"]["comment"].endswith("kaos-state=done rc=0"), "the host's own step finished normally"
    assert time.time() - t0 < 20 and "stopped by its run" in log, log


def test_a_step_over_its_memory_share_is_stopped_alone(tmp_path):
    hog = ("python3 -c \"b = bytearray(400 * 1024 * 1024)\nfor i in range(0, len(b), 4096): b[i] = 1\n"
           "import time; time.sleep(30)\"\n")
    guests = {"101": _job("kaos-%s-wf1-train" % SCOPE, hog, comment="kaos-commit=bbbbbbb2"),
              "102": _job("kaos-%s-wf2-train" % SCOPE, "sleep 2\nexit 0\n", comment="kaos-commit=bbbbbbb3")}
    node = Node(tmp_path, guests, mem_mb=1024)   # 256 MiB per slot
    rc, log = node.finish()
    assert rc == 0, log
    jobs = node.jobs()
    assert "kaos-state=done" in jobs["101"]["comment"] and "reason=memkill" in jobs["101"]["comment"], log
    assert "rc=0" not in jobs["101"]["comment"]
    assert jobs["102"]["comment"] == "kaos-commit=bbbbbbb3 kaos-state=done rc=0 host=100", "the neighbour finished"


def test_a_terminated_host_hands_its_guests_back_to_the_queue(tmp_path):
    guests = {"101": _job("kaos-%s-wf1-train" % SCOPE, "sleep 60\n", comment="kaos-commit=bbbbbbb2")}
    node = Node(tmp_path, guests, own_body="sleep 60\n")
    assert node.wait_for(lambda j: "kaos-state=taken" in j["101"]["comment"] and j["101"]["held"])
    node.proc.send_signal(signal.SIGTERM)   # walltime or scancel of the host: TERM, KILL 30 s later
    node.finish()
    j = node.jobs()["101"]
    assert j["state"] == "PENDING" and not j["held"], "back in the queue, free to run alone or on another host"
    assert j["comment"] == "kaos-commit=bbbbbbb2 kaos-state=requeued attempt=2", "next attempt, lease kept"


def test_a_requeued_job_is_claimed_under_its_new_attempt(tmp_path):
    guests = {"101": _job("kaos-%s-wf1-train" % SCOPE, "exit 0\n",
                          comment="kaos-commit=bbbbbbb2 kaos-state=requeued attempt=2")}
    (tmp_path / "scratch" / "kaos-claims" / "101-a1").mkdir(parents=True)   # the dead host's claim
    node = Node(tmp_path, guests)
    rc, log = node.finish()
    assert rc == 0, log
    assert node.jobs()["101"]["comment"] == "kaos-commit=bbbbbbb2 kaos-state=done rc=0 host=100"
    assert "took 101" in log, "taken although the dead host's attempt-1 lock is still there"
    assert (tmp_path / "scratch" / "kaos-claims" / "101-a1").is_dir(), "the dead host's lock is not ours to remove"
    assert not (tmp_path / "scratch" / "kaos-claims" / "101-a2").exists(), "our lock is removed once the job is done"


def test_squeue_time_limits_parse():
    g = {}
    exec(_slots_code().split("ME = os.environ")[0], g)   # helpers only, no host run
    exec("""
def limit_s(text):
""" + _slots_code().split("def limit_s(text):")[1].split("\ndef end_epoch")[0], g)
    f = g["limit_s"]
    assert f("10:00") == 600 and f("4:00:00") == 14400 and f("1-02:00:00") == 93600
    assert f("30") == 1800 and f("UNLIMITED") is None and f("") is None and f("bad") is None


def test_the_waiter_takes_a_hosts_own_result_while_its_job_still_runs():
    src = MELUXINA_SUBMIT_CODE
    loop = src[src.index("pending_reason = None"):]
    assert "elif 'RUNNING' in st and SHARING:" in loop
    assert "if any(x in TERMINAL for x in st) or ('RUNNING' in st and share.get('kaos-state') == 'done'):" in loop


def test_the_batch_step_becomes_the_host_only_with_slots():
    src = MELUXINA_SUBMIT_CODE
    assert "'if [ -z \"$KAOS_IN_STEP\" ] && [ -n \"$KAOS_SLOTS_B64\" ]; then'," in src
    sub = src[src.index("    commit = pinned_commit()\n    if commit:"):src.index("    body = {'job':")]
    assert "if SHARING and int(HPC.get('gpus') or 0) > 0:" in sub
    assert sub.index("KAOS_SLOTS_B64") < sub.index("batch, env = inputs_in_script(batch, env)"), \
        "the slot manager rides in the script, like every input"


def test_a_guest_killed_with_its_cancelled_host_is_requeued_not_failed(tmp_path):
    """Live 2026-11-03 (host 5417697): cancelling the host, Slurm killed the steps before the
    host's TERM handler ran, and the host recorded its guest's death as `done rc=143`. A run
    whose host went away must go back to the queue, however Slurm orders its signals."""
    guests = {"101": _job("kaos-%s-wf1-train" % SCOPE, "sleep 60\n", comment="kaos-commit=bbbbbbb2")}
    node = Node(tmp_path, guests, own_body="sleep 60\n")
    assert node.wait_for(lambda j: "kaos-state=taken" in j["101"]["comment"] and j["101"]["held"])
    end = time.time() + 20   # both steps (own + guest) are registered by srun
    while len(json.loads(node.state.read_text()).get("steps", {})) < 2 and time.time() < end:
        time.sleep(0.1)
    data = json.loads(node.state.read_text())
    assert len(data.get("steps", {})) == 2, data.get("steps")
    data["jobs"]["100"]["state"] = "CANCELLED"          # scancel of the host job ...
    node.state.write_text(json.dumps(data))
    for step in data.get("steps", {}).values():           # ... and Slurm TERMs its steps first
        os.killpg(step["pid"], signal.SIGTERM)
    node.finish()
    j = node.jobs()["101"]
    assert j["comment"] == "kaos-commit=bbbbbbb2 kaos-state=requeued attempt=2", j
    assert j["state"] == "PENDING" and not j["held"]


def test_a_guests_own_output_is_on_disk_when_its_step_reads_it(tmp_path):
    """Live 2026-11-03: fail() tails slurm-<job>.out, but srun forwards a step's output
    asynchronously, so the hosted error tail was empty. The step writes its log directly."""
    guests = {"101": _job("kaos-%s-wf1-train" % SCOPE,
                          "echo boom-from-the-step\ntail -c 200 $HOME/slurm-$KAOS_JOB_ID.out > $OUT/tail\nexit 0\n",
                          comment="kaos-commit=bbbbbbb2")}
    node = Node(tmp_path, guests)
    rc, log = node.finish()
    assert rc == 0, log
    assert "boom-from-the-step" in (node.out / "tail").read_text()


def test_every_step_has_its_login_basics(tmp_path):
    """Live 2026-11-03 (job 5417729): in a job with an explicit environment, a plain srun
    started the step with no HOME and cwd /, so fail()'s tail and every relative path broke.
    The slot manager exports its environment to the step; the launcher keeps only the basics."""
    guests = {"101": _job("kaos-%s-wf1-train" % SCOPE,
                          'echo "home=$HOME user=$USER pwd=$(pwd) path=${PATH:+set}" > $OUT/101\nexit 0\n',
                          comment="kaos-commit=bbbbbbb2")}
    node = Node(tmp_path, guests)
    rc, log = node.finish()
    assert rc == 0, log
    home = str(tmp_path / "home")
    got = (node.out / "101").read_text().split()
    import pwd
    # A login shell may reset USER from `id -un` (Fedora's /etc/profile); on MeluXina both are the job's user.
    assert got[0] == "home=" + home and got[1] in ("user=u104378", "user=" + pwd.getpwuid(os.getuid()).pw_name)
    assert got[2:] == ["pwd=" + home, "path=set"], got


def test_a_guest_fits_on_its_step_limit_not_its_padded_job_limit(tmp_path):
    """With sharing on every job asks Slurm for twice its step's time (so a host has room);
    the host fits a guest on the guest's own step limit (KAOS_STEP_LIMIT_MIN). With equal
    step limits the padded job limits alone would never fit."""
    pad = "export KAOS_STEP_LIMIT_MIN=10\n"
    guests = {
        # padded job limit 2 h > the host's remaining 1 h, but its step (10 min) fits
        "101": _job("kaos-%s-wf1-train" % SCOPE, pad + "exit 0\n", comment="kaos-commit=bbbbbbb2", limit="2:00:00"),
        # its step (3 h) does not fit: read once, never locked or held, skipped for good
        "102": _job("kaos-%s-wf2-train" % SCOPE, "export KAOS_STEP_LIMIT_MIN=180\nexit 0\n",
                    comment="kaos-commit=bbbbbbb3", limit="6:00:00"),
    }
    node = Node(tmp_path, guests, own_body="sleep 3\nexit 0\n", extra_env={"KAOS_IDLE_S": "2"})
    rc, log = node.finish()
    assert rc == 0, log
    jobs = node.jobs()
    assert jobs["101"]["comment"] == "kaos-commit=bbbbbbb2 kaos-state=done rc=0 host=100", log
    assert jobs["102"]["state"] == "PENDING" and not jobs["102"]["held"]
    calls = json.loads(node.state.read_text())["calls"]
    assert not [c for c in calls if c[:2] == ["scontrol", "hold"] and c[2] == "102"]
    reads = [c for c in calls if c[:3] == ["scontrol", "write", "batch_script"] and c[3] == "102"]
    assert len(reads) == 1, "a job that does not fit is not re-read every scan"
    steps = json.loads(node.state.read_text()).get("ended_steps", [])
    srun_101 = [c for c in calls if c[0] == "srun" and "kaos-101" in c]
    assert srun_101 and "--time=10" in srun_101[0], "the guest runs with its own step limit"


def test_memory_is_counted_as_pss(tmp_path):
    g = {}
    code = _slots_code()
    exec(code.split("ME = os.environ")[0] + "\nPAGE = os.sysconf('SC_PAGE_SIZE')\n"
         + code[code.index("def pss_bytes(pid):"):code.index("def step_rss():")], g)
    used = g["pss_bytes"](str(os.getpid()))
    assert 1 << 20 < used < 1 << 34, used
    assert "smaps_rollup" in code and "Pss:" in code


def test_every_step_is_told_its_slot(tmp_path):
    """PRD-1609 F-05: kaos_lib.runtime reads the step's share of the node from KAOS_SLOT_*
    (KUBECORE_SLOT_* is the deprecated alias an older kaos-lib reads)."""
    guests = {"101": _job("kaos-%s-wf1-train" % SCOPE,
                          'echo "$KAOS_SLOT_GPUS $KAOS_SLOT_CPUS $KAOS_SLOT_MEM_GIB $KAOS_SLOT_SHARED" > $OUT/101\n'
                          'echo "$KUBECORE_SLOT_GPUS $KUBECORE_SLOT_CPUS $KUBECORE_SLOT_MEM_GIB $KUBECORE_SLOT_SHARED" > $OUT/101-old\nexit 0\n',
                          comment="kaos-commit=bbbbbbb2")}
    node = Node(tmp_path, guests, mem_mb=491520)
    rc, log = node.finish()
    assert rc == 0, log
    assert (node.out / "101").read_text().split() == ["1", "32", "120", "1"]
    assert (node.out / "101-old").read_text().split() == ["1", "32", "120", "1"], "deprecated alias"
