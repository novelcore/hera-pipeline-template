"""PRD-HPC-1461 D-37/D-38/D-44: save progress before the Slurm time limit and continue the run.

* The job asks Slurm for USR1 before its limit (to the batch shell) and may be requeued by the site.
* The batch shell passes USR1 to the step's process group; a step whose kaos-lib run writer is open saves
  and exits 85; any other step ignores it and runs on.
* The waiter treats 85 as "continue": it submits the run again, a bounded number of times.

The launch lines are taken from the real job script and run in bash against a fake apptainer.
Run:  python -m pytest tests/ -v
"""
import ast
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kubecore.meluxina import MELUXINA_SUBMIT_CODE  # noqa: E402


def _job_script_lines():
    fn = next(n for n in ast.walk(ast.parse(MELUXINA_SUBMIT_CODE))
              if isinstance(n, ast.FunctionDef) and n.name == "submit")
    batch = next(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "batch")
    return [e.value for e in batch.value.args[0].elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def _launch_block():
    lines = _job_script_lines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith('[ -n "$STEP_CMD" ] ||'))
    end = lines.index("trap - USR1")
    return lines[start:end + 1]


HANDLER_STEP = ("python3 -c \"import signal,sys,time,pathlib; "
                "signal.signal(signal.SIGUSR1, lambda s,f: sys.exit(85)); "
                "pathlib.Path('ready').write_text('1'); time.sleep(30); sys.exit(3)\"")
PLAIN_STEP = "python3 -c \"import pathlib,time; pathlib.Path('ready').write_text('1'); time.sleep(2)\"; exit 0"


def _run(tmp_path, step_cmd):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # Like `apptainer exec [opts] SIF cmd...`: drop everything up to the image, run the rest. First it
    # starts a stand-in for Apptainer's squashfuse in the same process group, with USR1's default
    # action (die): live job 5421507 lost its image when the whole group was signalled.
    (bindir / "apptainer").write_text(
        '#!/bin/bash\nsleep 60 & echo $! > fuse.pid\n'
        'while [ "$1" != "$SIF" ]; do shift; done; shift; exec "$@"\n')
    (bindir / "apptainer").chmod(0o755)
    (bindir / "python3").symlink_to(sys.executable)
    script = "\n".join(_launch_block() + ['exit $rc'])
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


def test_the_job_asks_for_the_signal_and_requeue_except_on_a_host():
    submit = MELUXINA_SUBMIT_CODE[MELUXINA_SUBMIT_CODE.index("def submit():"):]
    block = submit[submit.index("if not hosting:"):submit.index("req = urllib.request.Request(API + '/job/submit'")]
    for field in ("'requeue': True", "'kill_warning_signal': 'USR1'", "'kill_warning_flags': ['BATCH_JOB']",
                  "CHECKPOINT_WARNING_S, step_limit * 30"):
        assert field in block
    assert "CHECKPOINT_WARNING_S = 10 * 60" in MELUXINA_SUBMIT_CODE


def test_nothing_is_staged_out_after_a_checkpoint_exit():
    stageout = next(ln for ln in _job_script_lines() if "STAGEOUT_B64" in ln and "base64 -d" in ln)
    assert stageout.startswith("if [ $rc -ne 85 ]")


def test_exit_85_continues_the_run_a_bounded_number_of_times():
    src = MELUXINA_SUBMIT_CODE
    assert "CHECKPOINT_EXIT = 85" in src and "MAX_CONTINUATIONS = 5" in src
    loop = src[src.index("if any(x in TERMINAL for x in st)"):]
    cont = loop[loop.index("if (rc == CHECKPOINT_EXIT"):loop.index("if 'COMPLETED' in st:")]
    assert "continuations < MAX_CONTINUATIONS" in cont and "jid = submit()" in cont and "continue" in cont
    assert "'CANCELLED'" in cont        # a stopped run is never continued


def test_the_waiters_deadline_covers_every_continuation():
    """Each continued job queues, prepares and runs again: a deadline sized for one job would kill
    the waiter in the middle of a continued run."""
    from kubecore import meluxina
    assert "MAX_CONTINUATIONS = %d" % meluxina.HPC_MAX_CONTINUATIONS in MELUXINA_SUBMIT_CODE
    src = Path(meluxina.__file__).read_text()
    assert ("(1 + HPC_MAX_CONTINUATIONS)\n                              * (minutes + QUEUE_ALLOWANCE_MINUTES) * 60"
            in src)
