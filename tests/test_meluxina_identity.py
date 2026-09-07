"""PRD-HPC-1231 CON-05: the MeluXina twin carries the PROJECT's HPC identity
from the pipeline context — never a literal user, account or path.
Run:  python -m pytest tests/ -v
"""

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kubecore import enhance  # noqa: E402

CONTEXT = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())
CATALOG = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "dataset-catalog.yaml").read_text())


def _enhanced(ctx):
    import runpy
    ns = runpy.run_path(str(ROOT / "pipeline.py"), run_name="__pipeline__")
    return enhance.enhance(yaml.safe_load(ns["p"].wt.to_yaml()), ctx, CATALOG)


def _twin_env(ctx):
    for t in _enhanced(ctx)["spec"]["templates"]:
        if t["name"] == "meluxina-run":
            return {e["name"]: e.get("value") for e in t["container"]["env"]}
    raise AssertionError("meluxina-run template not rendered")


def test_twin_carries_project_identity():
    env = _twin_env(CONTEXT)
    hpc = CONTEXT["hpc"]
    assert env["HPC_USER"] == hpc["user"]
    assert env["HPC_ACCOUNT"] == hpc["account"]
    assert env["HPC_SCRATCH"] == hpc["scratch"]
    assert env["HPC_HOME"] == hpc["home"]


def test_runner_has_no_identity_literals():
    src = (ROOT / "kubecore" / "meluxina.py").read_text()
    for literal in ("u104378", "p201342", "/home/users/u", "/project/scratch/p"):
        assert literal not in src, f"identity literal {literal!r} must come from the context"


def test_submit_refuses_without_identity():
    # The runner exits 2 (never submits as a default user) when the context
    # did not publish the tenancy. The runner is the embedded submit script
    # (MELUXINA_SUBMIT_CODE), so the function under test is extracted from it.
    import ast
    from kubecore import meluxina as m
    src = m.MELUXINA_SUBMIT_CODE
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "hpc_identity")
    code = "import os, sys\n" + ast.get_source_segment(src, fn) + "\nhpc_identity()\n"
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("HPC_")}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "HPC identity missing" in r.stdout
    env.update({"HPC_USER": "u1", "HPC_ACCOUNT": "p1", "HPC_SCRATCH": "/s", "HPC_HOME": "/h"})
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
