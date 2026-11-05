"""PRD-HPC-1461 D-44 as amended 2026-11-05: checkpoint and continue before the HPC (Slurm) wall time.

* Only a step declared ``step(..., resumable=True | "20m")`` gets the stop signal, its lead before the
  wall time, and only such a step continues.
* The batch shell passes USR1 only to the step's processes that handle it (never Apptainer's squashfuse).
* On exit 85 the job stages its checkpoint out to the outputs repository and commits it BEFORE it ends
  (T-19), then records the commit in its comment. 85 from a step that is not resumable fails, and so
  does a checkpoint that did not upload.
* The waiter continues only a resumable step, only from a committed checkpoint of THIS attempt, at most
  MAX_CONTINUATIONS times; the next job stages the checkpoint in and fails rather than start over.

The job-script lines and the on-node payloads are the real ones, run in bash/python against a fake
lakeFS server, a fake scontrol and a fake apptainer.
Run:  python -m pytest tests/ -v
"""
import ast
import base64
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kubecore.meluxina import MELUXINA_SUBMIT_CODE  # noqa: E402

SRC = MELUXINA_SUBMIT_CODE


def _job_script_lines():
    fn = next(n for n in ast.walk(ast.parse(SRC))
              if isinstance(n, ast.FunctionDef) and n.name == "submit")
    batch = next(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "batch")
    return [e.value for e in batch.value.args[0].elts      # the header line is computed
            if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def _block(first, last):
    lines = _job_script_lines()
    start = lines.index(first)
    return lines[start:lines.index(last, start) + 1]


def _payloads():
    ns = {}
    exec(SRC[SRC.index("CKPTOUT = r"):SRC.index("import base64, hashlib, json, os, re, shlex")], ns)
    return ns["CKPTOUT"], ns["CKPTIN"]


CKPTOUT, CKPTIN = _payloads()
FAIL = next(ln for ln in _job_script_lines() if ln.startswith("fail(){"))


# ---------------------------------------------------------------- a fake lakeFS (the calls the payloads make)

class FakeLakeFS:
    def __init__(self):
        self.objects = {}      # (branch, path) -> bytes
        self.commits = {}      # id -> {path: bytes}
        self.commit_meta = {}
        self.branches = set()
        self.fail_uploads = 0  # answer this many uploads with 500
        self.truncate = False  # serve object downloads one byte short
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b"", ctype="application/json"):
                if isinstance(body, (dict, list)):
                    body = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _parts(self):
                u = urllib.parse.urlsplit(self.path)
                return u.path.split("/")[3:], dict(urllib.parse.parse_qsl(u.query))

            def do_POST(self):
                assert self.headers["Authorization"] == "Bearer wallet"
                parts, q = self._parts()
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                # repositories/<repo>/branches
                if parts[2:] == ["branches"]:
                    name = json.loads(body)["name"]
                    if name in srv.branches:
                        return self._send(409, {})
                    srv.branches.add(name)
                    return self._send(201, {})
                # repositories/<repo>/branches/<b>/objects
                if parts[2] == "branches" and parts[4] == "objects":
                    if srv.fail_uploads:
                        srv.fail_uploads -= 1
                        return self._send(500, {})
                    head, rest = body.split(b"\r\n\r\n", 1)
                    assert rest.endswith(b"\r\n--B--\r\n") and b'name="content"' in head
                    srv.objects[(parts[3], q["path"])] = rest[:-len(b"\r\n--B--\r\n")]
                    return self._send(201, {})
                # repositories/<repo>/branches/<b>/commits
                if parts[2] == "branches" and parts[4] == "commits":
                    snap = {p: d for (b, p), d in srv.objects.items() if b == parts[3]}
                    cid = hashlib.sha256(repr(sorted(snap.items())).encode()).hexdigest()
                    srv.commits[cid] = snap
                    srv.commit_meta[cid] = json.loads(body)["metadata"]
                    return self._send(201, {"id": cid})
                self._send(404, {})

            def do_GET(self):
                assert self.headers["Authorization"] == "Bearer wallet"
                parts, q = self._parts()
                if parts[2] == "commits":
                    return self._send(200, {"id": parts[3]}) if parts[3] in srv.commits else self._send(404, {})
                ref = parts[3]
                view = srv.commits.get(ref) or {p: d for (b, p), d in srv.objects.items() if b == ref}
                if parts[4:] == ["objects", "stat"]:
                    d = view.get(q["path"])
                    return self._send(200, {"size_bytes": len(d)}) if d is not None else self._send(404, {})
                if parts[4:] == ["objects", "ls"]:
                    keys = sorted(k for k in view if k.startswith(q["prefix"]) and k > q.get("after", ""))
                    page, more = keys[:2], len(keys) > 2          # tiny pages: pagination is exercised
                    return self._send(200, {"results": [{"path": k, "path_type": "object",
                                                         "size_bytes": len(view[k])} for k in page],
                                            "pagination": {"has_more": more,
                                                           "next_offset": page[-1] if page else ""}})
                if parts[4:] == ["objects"]:
                    d = view.get(q["path"])
                    if d is None:
                        return self._send(404, {})
                    return self._send(200, d[:-1] if srv.truncate else d, "application/octet-stream")
                self._send(404, {})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def lakefs():
    srv = FakeLakeFS()
    yield srv
    srv.httpd.shutdown()


def _env(tmp_path, lakefs, **extra):
    env = dict(os.environ, LAKEFS_ENDPOINT=lakefs.url, LAKEFS_BEARER_TOKEN="wallet", OUTPUTS_REPO="outputs-app",
               OUTPUTS_REF="main", WF_UID="wf1", STEP_NAME="train", KAOS_ATTEMPT="2",
               KAOS_WORK=str(tmp_path / "work"), KAOS_CKPT_FILE=str(tmp_path / "ckpt.ref"))
    env.update(extra)
    return env


def _py(payload, env):
    """Run an on-node payload; retries sleep for nothing."""
    code = "import time; time.sleep = lambda s: None\n" + payload
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)


def _checkpoint(tmp_path, files):
    root = tmp_path / "work" / "output" / "checkpoint"
    for name, data in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)


BIG = os.urandom(3 * (1 << 20) + 17)     # more than one 1 MiB chunk, not a multiple of it
FILES = {"model.pt": BIG, "optim/state.bin": b"adam", "meta/epoch": b"7"}
PREFIX = "hpc-checkpoints/wf1/train/attempt-2/"


# ---------------------------------------------------------------- stage-out and stage-in payloads

def test_stage_out_uploads_every_file_and_commits_it(tmp_path, lakefs):
    _checkpoint(tmp_path, FILES)
    r = _py(CKPTOUT, _env(tmp_path, lakefs))
    assert r.returncode == 0, r.stdout + r.stderr
    cid, prefix = (tmp_path / "ckpt.ref").read_text().split()
    assert prefix == PREFIX
    assert lakefs.commits[cid] == {PREFIX + k: v for k, v in FILES.items()}
    assert "hpc-ckpt-wf1-train" in lakefs.branches, "kept on its own branch, never the hand-off branch"
    assert lakefs.commit_meta[cid] == {"kaos.kind": "checkpoint", "workflow_uid": "wf1", "step": "train",
                                       "attempt": "2"}


def test_a_later_attempt_reuses_the_branch(tmp_path, lakefs):
    lakefs.branches.add("hpc-ckpt-wf1-train")          # attempt 1 created it
    _checkpoint(tmp_path, FILES)
    assert _py(CKPTOUT, _env(tmp_path, lakefs)).returncode == 0


def test_a_failed_upload_is_retried(tmp_path, lakefs):
    lakefs.fail_uploads = 2
    _checkpoint(tmp_path, FILES)
    assert _py(CKPTOUT, _env(tmp_path, lakefs)).returncode == 0
    assert len(lakefs.commits) == 1


def test_an_upload_that_keeps_failing_commits_nothing(tmp_path, lakefs):
    lakefs.fail_uploads = 100
    _checkpoint(tmp_path, FILES)
    r = _py(CKPTOUT, _env(tmp_path, lakefs))
    assert r.returncode != 0 and not lakefs.commits and not (tmp_path / "ckpt.ref").exists()


def test_without_a_checkpoint_nothing_is_committed(tmp_path, lakefs):
    (tmp_path / "work" / "output" / "checkpoint").mkdir(parents=True)
    r = _py(CKPTOUT, _env(tmp_path, lakefs))
    assert r.returncode != 0 and "nothing in" in r.stdout and not lakefs.commits


def _staged_out(tmp_path, lakefs):
    _checkpoint(tmp_path, FILES)
    assert _py(CKPTOUT, _env(tmp_path, lakefs)).returncode == 0
    return (tmp_path / "ckpt.ref").read_text().split()


def test_stage_in_restores_the_checkpoint_at_its_commit(tmp_path, lakefs):
    cid, prefix = _staged_out(tmp_path, lakefs)
    lakefs.objects[("hpc-ckpt-wf1-train", PREFIX + "model.pt")] = b"changed after the commit"
    work = tmp_path / "next"
    r = _py(CKPTIN, _env(tmp_path, lakefs, KAOS_WORK=str(work), KAOS_RESUME_REF=cid, KAOS_RESUME_PREFIX=prefix))
    assert r.returncode == 0, r.stdout + r.stderr
    got = {p.relative_to(work / "resume").as_posix(): p.read_bytes()
           for p in (work / "resume").rglob("*") if p.is_file()}
    assert got == FILES, "exactly the committed files, nothing partial"


def test_stage_in_of_a_missing_checkpoint_fails(tmp_path, lakefs):
    r = _py(CKPTIN, _env(tmp_path, lakefs, KAOS_RESUME_REF="0" * 64, KAOS_RESUME_PREFIX=PREFIX))
    assert r.returncode != 0


def test_a_short_download_fails_and_leaves_no_file(tmp_path, lakefs):
    cid, prefix = _staged_out(tmp_path, lakefs)
    lakefs.truncate = True
    work = tmp_path / "next"
    r = _py(CKPTIN, _env(tmp_path, lakefs, KAOS_WORK=str(work), KAOS_RESUME_REF=cid, KAOS_RESUME_PREFIX=prefix))
    assert r.returncode != 0 and "short download" in r.stdout
    assert not [p for p in (work / "resume").rglob("*") if p.is_file() and not p.name.endswith(".part")]


# ---------------------------------------------------------------- the job script

def _bin(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "scontrol").write_text('#!/bin/bash\nprintf "%s\\n" "$@" >> "$SCONTROL_LOG"\n')
    (bindir / "scontrol").chmod(0o755)
    if not (bindir / "python3").exists():
        (bindir / "python3").symlink_to(sys.executable)
    return bindir


def _end_of_job(tmp_path, lakefs, rc, **extra):
    """The script from the step's exit code to the job's end."""
    block = _block('if [ $rc -eq 85 ]; then', 'exit 0')
    _checkpoint(tmp_path, FILES)
    env = _env(tmp_path, lakefs, PATH=str(_bin(tmp_path)) + os.pathsep + os.environ["PATH"],
               SCONTROL_LOG=str(tmp_path / "scontrol.log"), KAOS_JOB_ID="4242", KAOS_COMMIT="c0ffee12",
               CKPTOUT_B64=base64.b64encode(("import time; time.sleep = lambda s: None\n" + CKPTOUT).encode()).decode(),
               STEP_OUTPUTS="")
    env.pop("KAOS_CKPT_FILE")
    env.update(extra)
    script = "\n".join([FAIL, "rc=%d" % rc] + block)
    p = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True)
    log = (tmp_path / "scontrol.log").read_text() if (tmp_path / "scontrol.log").exists() else ""
    return p.returncode, log, p.stdout


def test_85_from_a_resumable_step_stages_the_checkpoint_out_before_the_job_ends(tmp_path, lakefs):
    rc, log, out = _end_of_job(tmp_path, lakefs, 85, KAOS_RESUMABLE="1")
    assert rc == 85, out
    (cid,) = lakefs.commits
    assert log.split("\n")[:3] == ["update", "JobId=4242",
                                   "Comment=kaos-commit=c0ffee12 kaos-ckpt=%s kaos-ckpt-path=%s" % (cid, PREFIX)]
    assert not (tmp_path / "work").exists(), "the job's scratch is removed once the checkpoint is committed"


def test_85_from_a_step_that_is_not_resumable_fails(tmp_path, lakefs):
    rc, log, out = _end_of_job(tmp_path, lakefs, 85)
    assert rc == 85 and "not declared resumable" in out
    assert "err85:" in log and "kaos-ckpt=" not in log and not lakefs.commits


def test_85_whose_checkpoint_does_not_upload_fails_235(tmp_path, lakefs):
    lakefs.fail_uploads = 100
    rc, log, _ = _end_of_job(tmp_path, lakefs, 85, KAOS_RESUMABLE="1")
    assert rc == 235 and "kaos-ckpt=" not in log and "err235:" in log


def test_85_without_a_wallet_fails_235(tmp_path, lakefs):
    rc, log, _ = _end_of_job(tmp_path, lakefs, 85, KAOS_RESUMABLE="1", LAKEFS_BEARER_TOKEN="")
    assert rc == 235 and not lakefs.commits


def test_a_step_that_finishes_ends_as_before(tmp_path, lakefs):
    rc, log, _ = _end_of_job(tmp_path, lakefs, 0, KAOS_RESUMABLE="1")
    assert rc == 0 and log == "" and not lakefs.commits


def _resume(tmp_path, lakefs, **extra):
    block = _block('if [ -n "$KAOS_RESUME_REF" ]; then', "fi")
    env = _env(tmp_path, lakefs, PATH=str(_bin(tmp_path)) + os.pathsep + os.environ["PATH"],
               SCONTROL_LOG=str(tmp_path / "scontrol.log"), KAOS_JOB_ID="4243", KAOS_WORK=str(tmp_path / "next"),
               CKPTIN_B64=base64.b64encode(CKPTIN.encode()).decode())
    env.update(extra)
    script = "\n".join([FAIL] + block + ['echo "resume=$APPTAINERENV_KAOS_RESUME_PATH"'])
    return subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True)


def test_a_continued_job_starts_from_the_checkpoint(tmp_path, lakefs):
    cid, prefix = _staged_out(tmp_path, lakefs)
    p = _resume(tmp_path, lakefs, KAOS_RESUME_REF=cid, KAOS_RESUME_PREFIX=prefix)
    assert p.returncode == 0 and "resume=/work/resume" in p.stdout
    assert (tmp_path / "next" / "resume" / "model.pt").read_bytes() == BIG


def test_a_continued_job_without_its_checkpoint_never_starts_from_scratch(tmp_path, lakefs):
    assert _resume(tmp_path, lakefs, KAOS_RESUME_REF="0" * 64, KAOS_RESUME_PREFIX=PREFIX).returncode == 234
    assert _resume(tmp_path, lakefs, KAOS_RESUME_REF="ab" * 32, KAOS_RESUME_PREFIX=PREFIX,
                   LAKEFS_BEARER_TOKEN="").returncode == 234


def test_a_first_job_has_no_resume_path(tmp_path, lakefs):
    p = _resume(tmp_path, lakefs)
    assert p.returncode == 0 and "resume=\n" in p.stdout


# ---------------------------------------------------------------- the stop signal reaches only handlers

HANDLER_STEP = ("python3 -c \"import signal,sys,time,pathlib; "
                "signal.signal(signal.SIGUSR1, lambda s,f: sys.exit(85)); "
                "pathlib.Path('ready').write_text('1'); time.sleep(30); sys.exit(3)\"")
PLAIN_STEP = "python3 -c \"import pathlib,time; pathlib.Path('ready').write_text('1'); time.sleep(2)\"; exit 0"


def _run(tmp_path, step_cmd):
    bindir = _bin(tmp_path)
    # Like `apptainer exec [opts] SIF cmd...`: drop everything up to the image, run the rest. First it
    # starts a stand-in for Apptainer's squashfuse in the same process group, with USR1's default
    # action (die): live job 5421507 lost its image when the whole group was signalled.
    (bindir / "apptainer").write_text(
        '#!/bin/bash\nsleep 60 & echo $! > fuse.pid\n'
        'while [ "$1" != "$SIF" ]; do shift; done; shift; exec "$@"\n')
    (bindir / "apptainer").chmod(0o755)
    script = "\n".join(_block('[ -n "$STEP_CMD" ] || STEP_CMD="nvidia-smi -L || nproc"', "trap - USR1")
                       + ['exit $rc'])
    env = dict(os.environ, SIF="img.sif", STEP_CMD=step_cmd, NV="", PWD_OPT="", BIND="",
               PATH=str(bindir) + os.pathsep + os.environ["PATH"])
    p = subprocess.Popen(["bash", "-c", script], cwd=tmp_path, env=env)
    for _ in range(200):
        if (tmp_path / "ready").exists():
            break
        time.sleep(0.05)
    os.kill(p.pid, signal.SIGUSR1)        # what Slurm does: the batch shell only (BATCH_JOB)
    rc = p.wait(timeout=30)
    fuse = int((tmp_path / "fuse.pid").read_text())
    try:
        os.kill(fuse, 0)                  # still alive: the signal only went to handlers
        alive = True
    except ProcessLookupError:
        alive = False
    finally:
        try:
            os.kill(fuse, signal.SIGKILL)
        except ProcessLookupError:
            pass
    assert alive, "a process without a USR1 handler was signalled (Apptainer's squashfuse would die)"
    return rc


def test_the_stop_signal_reaches_a_step_inside_the_container_and_85_comes_back(tmp_path):
    assert _run(tmp_path, HANDLER_STEP) == 85


def test_a_step_without_a_handler_ignores_the_signal_and_finishes(tmp_path):
    assert _run(tmp_path, PLAIN_STEP) == 0


# ---------------------------------------------------------------- submit: only a resumable step is signalled

def _runner(monkeypatch, **env):
    for k in ("HPC_SHARING", "HPC_SCOPE", "HPC_RESUMABLE_LEAD"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    g = {}
    exec(SRC.split("API = ")[0], g)
    return g


def test_only_a_resumable_step_asks_for_the_signal_at_its_lead():
    sub = SRC[SRC.index("def submit():"):SRC.index("req = urllib.request.Request(API + '/job/submit'")]
    tail = sub[sub.index("    if not hosting:"):]
    assert "body['job']['requeue'] = True" in tail.split("    if RESUMABLE_LEAD_MIN:")[0]
    signalled = tail.split("    if RESUMABLE_LEAD_MIN:")[1]
    for field in ("'kill_warning_signal': 'USR1'", "'kill_warning_flags': ['BATCH_JOB']",
                  "'number': RESUMABLE_LEAD_MIN * 60"):
        assert field in signalled
    assert sub.count("kill_warning_signal") == 1


def test_the_job_carries_its_attempt_and_resume_point():
    sub = SRC[SRC.index("def submit():"):]
    assert "'KAOS_ATTEMPT=%d' % ATTEMPT" in sub
    assert "env += ['KAOS_RESUME_REF=' + RESUME[0], 'KAOS_RESUME_PREFIX=' + RESUME[1]]" in sub
    assert "env.append('KAOS_RESUMABLE=1')" in sub


def test_the_lead_comes_from_the_render(monkeypatch):
    assert _runner(monkeypatch)["RESUMABLE_LEAD_MIN"] == 0
    assert _runner(monkeypatch, HPC_RESUMABLE_LEAD="20")["RESUMABLE_LEAD_MIN"] == 20


def test_a_resumable_step_never_shares_a_node(monkeypatch, capsys):
    """A host's slot manager does not pass the signal on (#1609)."""
    assert _runner(monkeypatch, HPC_SHARING="on", HPC_SCOPE="a1b2c3d4e5")["SHARING"] is True
    assert _runner(monkeypatch, HPC_SHARING="on", HPC_SCOPE="a1b2c3d4e5",
                   HPC_RESUMABLE_LEAD="10")["SHARING"] is False
    assert "it is resumable" in capsys.readouterr().out


# ---------------------------------------------------------------- the waiter: when a step continues

def _waiter_fns(comments, live=None, lakefs=None, attempt=2):
    """checkpoint_path / checkpoint_of / checkpoint_committed with the Slurm reads faked: comments is
    the sequence of accounting comments the polls see, live the slurmctld comment (None: unreachable)."""
    tree = ast.parse(SRC)
    src = "\n\n".join(ast.get_source_segment(SRC, n) for n in tree.body
                      if isinstance(n, ast.FunctionDef)
                      and n.name in ("comment_of", "checkpoint_path", "checkpoint_of", "checkpoint_committed"))
    seen = iter(comments[1:] + comments[-1:] * 10)

    def get(url):
        if url.startswith("SDB"):
            return {"jobs": [{"comment": {"job": next(seen)}}]}
        if live is None:
            raise OSError("slurmctld unreachable")
        return {"jobs": [{"comment": live}]}

    import urllib.error
    import urllib.request
    g = {"os": os, "re": re, "json": json, "time": type("T", (), {"sleep": staticmethod(lambda s: None)}),
         "urllib": urllib, "get": get, "API": "API", "SDB": "SDB", "ATTEMPT": attempt, "WALLET": "wallet"}
    os.environ.update(WF_UID="wf1", STEP_NAME="train", OUTPUTS_REPO="outputs-app",
                      LAKEFS_EXTERNAL_URL=lakefs.url if lakefs else "http://127.0.0.1:9")
    exec(src, g)
    return g, {"comment": {"job": comments[0]}}


CID = "ab" * 32


def test_the_checkpoint_of_this_attempt_is_found():
    g, job = _waiter_fns(["kaos-commit=c0ffee12 kaos-ckpt=%s kaos-ckpt-path=%s" % (CID, PREFIX)])
    assert g["checkpoint_of"](job, 1) == (CID, PREFIX)


def test_lagging_accounting_is_covered_by_slurmctld_and_by_asking_again():
    comment = "kaos-ckpt=%s kaos-ckpt-path=%s" % (CID, PREFIX)
    g, job = _waiter_fns(["kaos-commit=c0ffee12"], live=comment)
    assert g["checkpoint_of"](job, 1) == (CID, PREFIX)
    g, job = _waiter_fns(["kaos-commit=c0ffee12", "kaos-commit=c0ffee12", comment])
    assert g["checkpoint_of"](job, 1) == (CID, PREFIX)


@pytest.mark.parametrize("comment", [
    "kaos-commit=c0ffee12",                                                        # never uploaded
    "kaos-commit=c0ffee12 err235:upload failed",                                   # upload failed
    "kaos-ckpt=%s kaos-ckpt-path=hpc-checkpoints/wf1/train/attempt-1/" % CID,      # the previous attempt's
    "kaos-ckpt=%s kaos-ckpt-path=hpc-checkpoints/wf1/eval/attempt-2/" % CID,       # another step's
    "kaos-ckpt=not-a-commit kaos-ckpt-path=%s" % PREFIX,
])
def test_no_checkpoint_of_this_attempt_means_no_continuation(comment):
    g, job = _waiter_fns([comment])
    assert g["checkpoint_of"](job, 1) is None


def test_the_checkpoint_commit_must_exist(tmp_path, lakefs):
    cid, _ = _staged_out(tmp_path, lakefs)
    g, _ = _waiter_fns([""], lakefs=lakefs)
    assert g["checkpoint_committed"](cid) is True
    assert g["checkpoint_committed"]("cd" * 32) is False


def test_an_unreachable_lakefs_never_lets_the_step_continue():
    g, _ = _waiter_fns([""])
    assert g["checkpoint_committed"](CID) is False


def test_the_waiter_continues_only_a_resumable_step_from_a_committed_checkpoint_under_the_cap():
    loop = SRC[SRC.index("if any(x in TERMINAL for x in st)"):]
    cont = loop[loop.index("if rc == CHECKPOINT_EXIT"):loop.index("if 'COMPLETED' in st:")]
    assert "'CANCELLED'" in cont                                  # a stopped run is never continued
    order = [cont.index(s) for s in ("if not RESUMABLE_LEAD_MIN:", "elif not ckpt:",
                                     "elif not checkpoint_committed(ckpt[0]):",
                                     "elif continuations >= MAX_CONTINUATIONS:", "if why:",
                                     "sys.exit(1)", "ATTEMPT += 1", "RESUME = ckpt", "jid = submit()")]
    assert order == sorted(order)
    assert "CHECKPOINT_EXIT = 85" in SRC and "MAX_CONTINUATIONS = 5" in SRC


# ---------------------------------------------------------------- authoring and render

def _render(**kw):
    from kubecore import authoring, enhance
    with authoring.pipeline("t") as p:
        authoring.step("train", gpu=True, **kw)
    ctx = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())
    wft = enhance.enhance(yaml.safe_load(p.wt.to_yaml()), ctx)
    for t in wft["spec"]["templates"]:
        for task in (t.get("dag") or {}).get("tasks") or []:
            if task["name"] == "train-meluxina":
                return {a["name"]: a["value"] for a in task["arguments"]["parameters"]}
    raise AssertionError("no HPC twin rendered")


@pytest.mark.parametrize("value, lead", [(True, "10m"), ("20m", "20m"), ("1h", "1h"), ("15", "15")])
def test_resumable_is_an_annotation(value, lead):
    from kubecore import authoring
    with authoring.pipeline("t") as p:
        authoring.step("train", gpu=True, resumable=value)
    (tmpl,) = [t for t in yaml.safe_load(p.wt.to_yaml())["spec"]["templates"] if t["name"] == "train"]
    assert tmpl["metadata"]["annotations"][authoring.HPC_RESUMABLE_ANNOTATION] == lead


@pytest.mark.parametrize("value", ["0m", "00", "soon", 10, "10s"])
def test_a_bad_lead_is_refused(value):
    from kubecore import authoring
    with pytest.raises(authoring.AuthoringError), authoring.pipeline("t"):
        authoring.step("train", gpu=True, resumable=value)


def test_resumable_needs_a_gpu_step():
    from kubecore import authoring
    with pytest.raises(authoring.AuthoringError), authoring.pipeline("t"):
        authoring.step("prep", resumable=True)


def test_a_resumable_steps_waiter_gets_its_lead_and_a_deadline_for_every_continuation():
    from kubecore import meluxina
    plain = _render(hpc_time_limit="2h")
    assert plain["resumable-lead"] == "0"
    assert int(plain["deadline-seconds"]) == (120 + meluxina.QUEUE_ALLOWANCE_MINUTES) * 60
    resumable = _render(hpc_time_limit="2h", resumable="20m")
    assert resumable["resumable-lead"] == "20"
    assert int(resumable["deadline-seconds"]) == \
        (1 + meluxina.HPC_MAX_CONTINUATIONS) * (120 + meluxina.QUEUE_ALLOWANCE_MINUTES) * 60
    assert "MAX_CONTINUATIONS = %d" % meluxina.HPC_MAX_CONTINUATIONS in SRC


def test_a_lead_not_shorter_than_the_wall_time_is_refused():
    with pytest.raises(ValueError, match="not shorter than its wall time"):
        _render(hpc_time_limit="30m", resumable="30m")
