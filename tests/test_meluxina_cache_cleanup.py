"""PRD-HPC-1541: the MeluXina job script cleans its image and download caches by
last use. The SIF cache, Apptainer's layer cache and the in-job download cache
share the allocation's scratch quota with the dataset cache and only ever grew
(154 GiB of 157 on 2026-10-25).

The cleanup lines are taken from the real job script and run in bash against a
fake scratch.
Run:  python -m pytest tests/ -v
"""
import ast
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kubecore.meluxina import MELUXINA_SUBMIT_CODE  # noqa: E402

OLD = time.time() - 20 * 86400


def _job_script_lines():
    """The literal lines of submit()'s batch script."""
    fn = next(n for n in ast.walk(ast.parse(MELUXINA_SUBMIT_CODE))
              if isinstance(n, ast.FunctionDef) and n.name == "submit")
    batch = next(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "batch")
    return [e.value for e in batch.value.args[0].elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def _make(path, old):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    if old:
        os.utime(path, (OLD, OLD))


def test_caches_are_cleaned_by_last_use(tmp_path):
    lines = _job_script_lines()
    cleanup = [l for l in lines if l.startswith(("touch -c", "find $SCR/", "apptainer cache clean"))]
    assert len(cleanup) == 4, cleanup
    scr = tmp_path / "scratch"
    _make(scr / "sif-cache" / "old.sif", old=True)
    _make(scr / "sif-cache" / "recent.sif", old=False)
    _make(scr / "sif-cache" / "inuse.sif", old=True)        # this job's image
    _make(scr / "data-cache" / "repo" / "c1" / ".complete", old=True)
    _make(scr / "data-cache" / "repo" / "c1" / "f", old=True)
    _make(scr / "data-cache" / "repo" / "c2" / ".complete", old=False)
    _make(scr / "data-cache" / "repo" / "c3" / "partial", old=True)  # no marker: left alone
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "apptainer").write_text('#!/bin/sh\necho "$@" > "$SCR/apptainer-args"\n')
    (bindir / "apptainer").chmod(0o755)
    env = dict(os.environ, SCR=str(scr), SIF=str(scr / "sif-cache" / "inuse.sif"),
               USER=os.environ.get("USER") or os.getlogin(),
               PATH=str(bindir) + os.pathsep + os.environ["PATH"])
    subprocess.run(["bash", "-c", "\n".join(cleanup)], env=env, check=True)

    assert sorted(p.name for p in (scr / "sif-cache").iterdir()) == ["inuse.sif", "recent.sif"]
    assert sorted(p.name for p in (scr / "data-cache" / "repo").iterdir()) == ["c2", "c3"]
    assert (scr / "apptainer-args").read_text().split() == ["cache", "clean", "--force", "--days", "14"]


def test_this_jobs_image_and_download_are_touched_before_the_cleanup():
    lines = _job_script_lines()
    touch = lines.index('touch -c "$SIF"')
    first_clean = next(i for i, l in enumerate(lines) if l.startswith("find $SCR/"))
    assert touch < first_clean
    assert "(dest / '.complete').touch()" in MELUXINA_SUBMIT_CODE
