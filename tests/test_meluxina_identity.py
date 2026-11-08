"""PRD-HPC-1231 CON-05, PRD-HPC-1461 F-35: the MeluXina twin holds no HPC identity.
The project's user, account and filesystem layout reach the site through the controller's HPCSite,
never through the pipeline template, and the module carries no literal user, account or path.
Run:  python -m pytest tests/ -v
"""

import runpy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kubecore import enhance  # noqa: E402

CONTEXT = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())


def _twin_env(ctx):
    ns = runpy.run_path(str(ROOT / "pipeline.py"), run_name="__pipeline__")
    wf = enhance.enhance(yaml.safe_load(ns["p"].wt.to_yaml()), ctx)
    for t in wf["spec"]["templates"]:
        if t["name"] == "hpc-follower":
            return {e["name"]: e.get("value") for e in t["container"]["env"]}
    raise AssertionError("hpc-follower template not rendered")


def test_twin_carries_no_project_identity():
    env = _twin_env(CONTEXT)
    for name in ("HPC_USER", "HPC_ACCOUNT", "HPC_SCRATCH", "HPC_HOME"):
        assert name not in env, name
    values = " ".join(str(v) for v in env.values())
    for v in (CONTEXT["hpc"]["user"], CONTEXT["hpc"]["account"]):
        assert v not in values


def test_module_has_no_identity_literals():
    src = (ROOT / "kubecore" / "meluxina.py").read_text()
    for literal in ("u104378", "p201342", "/home/users/u", "/project/scratch/p"):
        assert literal not in src, f"identity literal {literal!r} must come from the context"
