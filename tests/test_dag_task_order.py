"""The entrypoint DAG lists every task after the tasks it depends on.

Argo's controller does not care about task order, but the Argo UI's
WorkflowTemplate graph view walks dag.tasks top to bottom and dereferences
each dependency's node, which only exists if it was listed earlier. A task
that depends on one listed further down crashes the view with
"Cannot read properties of undefined (reading 'genre')". The MeluXina twins
used to be appended at the end, so every step after the first did that.
Run:  python -m pytest tests/ -v
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kubecore import enhance  # noqa: E402

CONTEXT = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())
CATALOG = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "dataset-catalog.yaml").read_text())

_STATUS = r"Succeeded|Failed|Errored|Skipped|Omitted|Daemoned|AnySucceeded|AllFailed"


def _depends_on(expr):
    expr = re.sub(r"\.(%s)\b" % _STATUS, "", expr or "")
    return set(re.findall(r"[A-Za-z0-9][\w-]*", expr))


def _dag_tasks():
    import runpy
    ns = runpy.run_path(str(ROOT / "pipeline.py"), run_name="__pipeline__")
    spec = enhance.enhance(yaml.safe_load(ns["p"].wt.to_yaml()), CONTEXT, CATALOG)["spec"]
    entry = next(t for t in spec["templates"] if t["name"] == spec["entrypoint"])
    return entry["dag"]["tasks"]


def test_example_pipeline_has_hpc_twins():
    # Guard: the order test below is only meaningful when twins are rendered.
    assert any(t["name"].endswith("-meluxina") for t in _dag_tasks())


def test_every_dependency_is_listed_before_its_dependent():
    seen = set()
    for task in _dag_tasks():
        deps = _depends_on(task.get("depends")) | set(task.get("dependencies") or [])
        missing = deps - seen
        assert not missing, f"{task['name']} depends on {sorted(missing)} listed after it"
        seen.add(task["name"])


def test_twin_follows_its_in_cluster_task():
    names = [t["name"] for t in _dag_tasks()]
    for i, name in enumerate(names):
        if name.endswith("-meluxina"):
            assert names[i - 1] == name[: -len("-meluxina")]
