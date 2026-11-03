"""PRD-HPC-1609 F-01 / F-04: the MeluXina job script and waiter, ready for node sharing.

With sharing off (every project today) the job runs exactly as before, with two
behaviour-neutral changes: per-job paths key on KAOS_JOB_ID (= SLURM_JOB_ID on the job's
own node) and the failure comment keeps the dataset lease. With sharing on (the operator
publishes hpc.sharing=on and the project's scope), the job name carries the scope and the
inputs ride in the script, because a host can read a waiting job's script but not its
environment (live probe 2026-11-03). The waiter reads a host's result from the comment.
Run:  python -m pytest tests/ -v
"""
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kubecore import enhance, meluxina  # noqa: E402
from kubecore.meluxina import MELUXINA_SUBMIT_CODE  # noqa: E402

# The dataset stager's lease pattern (images/meluxina-tokenmint/stager/stager.py, LEASE_RE),
# applied with findall over `squeue -o %k`.
LEASE_RE = re.compile(r'kaos-commit=([0-9a-f]{6,64})')


def _job_script_lines():
    fn = next(n for n in ast.walk(ast.parse(MELUXINA_SUBMIT_CODE))
              if isinstance(n, ast.FunctionDef) and n.name == "submit")
    batch = next(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "batch")
    return [e.value for e in batch.value.args[0].elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def _runner(monkeypatch, **env):
    """The runner's module-level helpers (everything before the Slurm API section)."""
    for k in ("HPC_SHARING", "HPC_SCOPE"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    g = {}
    exec(MELUXINA_SUBMIT_CODE.split("API = ")[0], g)
    return g


# ---------------------------------------------------------------- F-01 job script

def test_per_job_paths_key_on_the_steps_own_job():
    lines = _job_script_lines()
    assert lines.index("set +e") < lines.index("KAOS_JOB_ID=${KAOS_JOB_ID:-$SLURM_JOB_ID}") \
        < next(i for i, l in enumerate(lines) if l.startswith("fail(){"))
    # The batch step's own id is used only by the default itself, the pull's private
    # temp name (unique per process anyway) and the host hook (F-03), which runs in the
    # batch step before any step exists.
    hook = lines[lines.index('if [ -z "$KAOS_IN_STEP" ] && [ -n "$KAOS_SLOTS_B64" ]; then'):]
    hook = hook[:hook.index("fi") + 1]
    uses = [l for l in lines if "$SLURM_JOB_ID" in l and l not in hook]
    assert len(uses) == 2 and any(l.startswith("KAOS_JOB_ID=") for l in uses) \
        and any("SIF_TMP=" in l for l in uses), uses
    assert any("kaos-work/$KAOS_JOB_ID" in l for l in lines)
    assert any("ds-$KAOS_JOB_ID.dir" in l for l in lines)


def test_the_script_header_names_format_and_scope():
    assert "'# kaos-job v2 scope=' + (SCOPE if SHARING else '-')" in MELUXINA_SUBMIT_CODE


@pytest.mark.parametrize("commit, expected_prefix", [("c0ffee12", "kaos-commit=c0ffee12 err7:"), ("", "err7:")])
def test_a_failure_comment_keeps_the_dataset_lease(tmp_path, commit, expected_prefix):
    fail = next(l for l in _job_script_lines() if l.startswith("fail(){"))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "scontrol").write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$OUT"\n')
    (bindir / "scontrol").chmod(0o755)
    (tmp_path / "slurm-4242.out").write_text("pulling\nboom\n")
    env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"], OUT=str(tmp_path / "args"),
               KAOS_JOB_ID="4242", KAOS_COMMIT=commit)
    rc = subprocess.run(["bash", "-c", fail + "\nfail 7"], cwd=tmp_path, env=env).returncode
    assert rc == 7
    args = (tmp_path / "args").read_text().split("\n")
    assert args[:2] == ["update", "JobId=4242"], "the comment goes to the step's own job, also on a host"
    comment = args[2]
    assert comment.startswith("Comment=" + expected_prefix) and "boom" in comment
    assert LEASE_RE.findall(comment) == ([commit] if commit else [])


def test_sharing_stays_off_without_a_valid_scope(monkeypatch, capsys):
    assert _runner(monkeypatch)["SHARING"] is False
    assert _runner(monkeypatch, HPC_SHARING="on")["SHARING"] is False
    assert _runner(monkeypatch, HPC_SHARING="on", HPC_SCOPE="Bad Scope!")["SHARING"] is False
    assert "running alone" in capsys.readouterr().out
    assert _runner(monkeypatch, HPC_SHARING="off", HPC_SCOPE="a1b2c3d4e5")["SHARING"] is False
    assert _runner(monkeypatch, HPC_SHARING="on", HPC_SCOPE="a1b2c3d4e5")["SHARING"] is True


def test_the_job_name_carries_the_scope_only_with_sharing_on():
    assert ("jobname = 'kaos-' + (SCOPE + '-' if SHARING else '') + os.environ['WF_UID']"
            in MELUXINA_SUBMIT_CODE)
    sub = MELUXINA_SUBMIT_CODE
    body = sub[sub.index("    commit = pinned_commit()\n    if commit:"):sub.index("    req = urllib.request.Request(API + '/job/submit'")]
    assert "if SHARING:\n        batch, env = inputs_in_script(batch, env)" in body


def test_inputs_ride_in_the_script_and_survive_any_value(monkeypatch, tmp_path):
    g = _runner(monkeypatch, HPC_SHARING="on", HPC_SCOPE="a1b2c3d4e5")
    tricky = "python -c 'print(\"a b\")' && echo $HOME \\\n `x` ; done"
    env = ["PATH=/usr/bin:/bin", "HOME=/home/u", "USER=u", "STEP_CMD=" + tricky,
           "LAKEFS_BEARER_TOKEN=eyJ.a=b.c", "EMPTY="]
    batch = "\n".join(["#!/bin/bash -l", "# kaos-job v2 scope=a1b2c3d4e5", "set +e",
                       "KAOS_JOB_ID=${KAOS_JOB_ID:-$SLURM_JOB_ID}",
                       'printf "%s|%s|%s|%s" "$STEP_CMD" "$LAKEFS_BEARER_TOKEN" "${EMPTY-unset}" "$HOME" > "$OUT"'])
    script, slurm_env = g["inputs_in_script"](batch, env)
    assert slurm_env == ["PATH=/usr/bin:/bin", "HOME=/home/u", "USER=u"], "secrets leave the Slurm environment"
    lines = script.split("\n")
    assert lines[:3] == ["#!/bin/bash -l", "# kaos-job v2 scope=a1b2c3d4e5", "set +e"], "header stays on top"
    assert not any(l.startswith(("export PATH=", "export HOME=", "export USER=")) for l in lines), \
        "the login shell's PATH is never overwritten"
    (tmp_path / "job.sh").write_text(script)
    out = tmp_path / "out"
    subprocess.run(["bash", str(tmp_path / "job.sh")], check=True,
                   env={"PATH": os.environ["PATH"], "HOME": "/home/u", "OUT": str(out)})
    assert out.read_text() == tricky + "|eyJ.a=b.c||/home/u"


# ---------------------------------------------------------------- F-04 waiter

def test_a_hosts_comment_is_read_as_state(monkeypatch):
    g = _runner(monkeypatch)
    share, comment_of = g["share_state"], g["comment_of"]
    assert share("kaos-commit=c0ffee12") == {}
    assert share("err231:pull failed|") == {}
    assert share("kaos-commit=c0ffee12 kaos-state=taken host=5417591 slot=2 attempt=1") == \
        {"kaos-state": "taken", "host": "5417591", "slot": "2", "attempt": "1"}
    assert share("kaos-state=done rc=0 host=5417591") == {"kaos-state": "done", "rc": "0", "host": "5417591"}
    assert share("kaos-commit=c0ffee12 kaos-state=done rc=137 err=killed|") ["rc"] == "137"
    assert comment_of({"comment": {"job": "kaos-state=done rc=0", "administrator": ""}}) == "kaos-state=done rc=0"
    assert comment_of({"comment": "kaos-state=taken"}) == "kaos-state=taken"
    assert comment_of({}) == ""
    for c in ("kaos-commit=c0ffee12 kaos-state=taken host=1 slot=0 attempt=1",
              "kaos-commit=c0ffee12 kaos-state=done rc=0"):
        assert LEASE_RE.findall(c) == ["c0ffee12"], "every host write keeps the dataset lease"


def _loop():
    src = MELUXINA_SUBMIT_CODE
    return src[src.index("pending_reason = None"):src.index("def _tag_expr") if "def _tag_expr" in src else None]


def test_a_taken_job_is_never_resubmitted_for_its_token():
    loop = _loop()
    start = loop.index("# A job a host took")
    resubmit = loop[start:loop.index("cancel(jid)", start)]
    assert "share.get('kaos-state') != 'taken'" in resubmit


def test_a_hosts_done_comment_is_the_steps_result():
    loop = _loop()
    terminal = loop[loop.index("if any(x in TERMINAL for x in st)"):]
    done = terminal.index("if share.get('kaos-state') == 'done':")
    assert done < terminal.index("if 'FAILED' in st and rc == 231"), \
        "a host's pull failure still gets the fresh-credentials resubmit"
    assert done < terminal.index("fetch_outputs()"), "a hosted success fetches its outputs as usual"
    assert "st = ['COMPLETED'] if rc == 0 else ['FAILED']" in terminal


# ---------------------------------------------------------------- enhancer

CONTEXT = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())


def _twin_env(ctx):
    import runpy
    ns = runpy.run_path(str(ROOT / "pipeline.py"), run_name="__pipeline__")
    wf = enhance.enhance(yaml.safe_load(ns["p"].wt.to_yaml()), ctx)
    twin = next(t for t in wf["spec"]["templates"] if t["name"] == "meluxina-run")
    return {e["name"]: e.get("value") for e in twin["container"]["env"]}


def test_without_sharing_the_waiter_renders_as_before():
    assert meluxina.sharing_env(CONTEXT) == []
    assert meluxina.sharing_env({"hpc": {"sharing": "on"}}) == [], "no scope, no sharing"
    assert meluxina.sharing_env({"hpc": {"sharing": "off", "scope": "a1b2c3d4e5"}}) == []
    env = _twin_env(CONTEXT)
    assert "HPC_SHARING" not in env and "HPC_SCOPE" not in env


def test_the_operators_switch_reaches_the_waiter():
    ctx = dict(CONTEXT, hpc=dict(CONTEXT.get("hpc") or {}, sharing="on", scope="a1b2c3d4e5"))
    env = _twin_env(ctx)
    assert env["HPC_SHARING"] == "on" and env["HPC_SCOPE"] == "a1b2c3d4e5"
    assert meluxina.sharing_env({"hpc": {"sharing": True, "scope": "a1b2c3d4e5"}})[0]["value"] == "on", \
        "a bare YAML on (read as True) still means on"


# ---------------------------------------------------------------- lost host (PRD-1609)

def _host_gone(records):
    """host_gone() from the waiter, with accounting answered from `records`."""
    tree = ast.parse(MELUXINA_SUBMIT_CODE)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "host_gone")
    alive = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "HOST_ALIVE")
    g = {"SDB": "https://sdb"}

    def get(url):
        rec = records[url.rsplit("/", 1)[1]]
        if isinstance(rec, Exception):
            raise rec
        return {"jobs": [{"state": {"current": rec}}]}
    g["get"] = get
    exec(compile(ast.Module(body=[alive, fn], type_ignores=[]), "waiter", "exec"), g)
    return g["host_gone"]


def test_a_host_is_gone_only_when_accounting_says_it_ended():
    gone = _host_gone({"1": ["RUNNING"], "2": ["COMPLETING"], "3": ["NODE_FAIL"], "4": ["CANCELLED"],
                       "5": ["COMPLETED"], "6": [], "7": OSError("REST down"), "8": ["PENDING"]})
    assert not gone("1") and not gone("2") and not gone("8"), "a live host is never given up on"
    assert gone("3") and gone("4") and gone("5"), "a host that ended without handing the job back is gone"
    assert not gone("6") and not gone("7"), "an unreadable or empty record is not a death"


def test_a_job_whose_host_died_starts_over_with_the_proven_calls():
    loop = _loop()
    lost = loop[loop.index("lost_hosts < LOST_HOST_RESUBMITS"):loop.index("# A job a host took")]
    assert "cancel(jid)" in lost and "jid = submit()" in lost and "continue" in lost
    assert "lost_hosts += 1" in lost, "bounded: a run starts over at most LOST_HOST_RESUBMITS times"
    assert "share.get('kaos-state') == 'taken'" in loop[loop.index("if ('PENDING' in st and share.get('kaos-state') == 'taken'"):][:200]
    assert "LOST_HOST_RESUBMITS = 3" in MELUXINA_SUBMIT_CODE


def test_a_sharing_job_asks_for_twice_its_step_time_capped_by_the_class():
    sub = MELUXINA_SUBMIT_CODE
    body = sub[sub.index("    step_limit = int(os.environ.get('SLURM_TIME_LIMIT') or 240)"):sub.index("    body = {'job':")]
    assert "'KAOS_STEP_LIMIT_MIN=%d' % step_limit" in body
    assert "cap = int(HPC.get('maxTimeLimitMinutes') or 0)" in body
    assert "job_limit = max(step_limit, min(2 * step_limit, cap))" in body
    assert "'time_limit': job_limit," in sub
    # the computation itself
    for step, cap, want in [(240, 2880, 480), (240, 300, 300), (240, 0, 240), (240, 100, 240)]:
        job = max(step, min(2 * step, cap)) if cap else step
        assert job == want, (step, cap, job)
