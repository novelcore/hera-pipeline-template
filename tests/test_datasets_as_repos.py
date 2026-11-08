"""Platform side of datasets as repositories (PRD novelcore/kaos#1283 F-07).

These files are pinned by the platform CI for EVERY ML app: a run picks
`<dataset-repo>@<version>` (the `dataset` parameter), the HPC follower hands it to the controller,
and every result goes to `outputs-<app>` on `main`. The stage-in/stage-out code that read these
values moved to the controller's runner (PRD-HPC-1461 F-35).
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kubecore.enhance import enhance  # noqa: E402

CTX_PATH = ROOT / "kubecore/local-dev/pipeline-context.yaml"


# ---------------------------------------------------------------- render wiring

def _raw():
    return {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "WorkflowTemplate", "metadata": {"name": "x"},
        "spec": {"entrypoint": "p", "arguments": {"parameters": [{"name": "dataset", "value": "dataset-default@latest"}]},
                 "templates": [
            {"name": "p", "dag": {"tasks": [{"name": "model-training", "template": "model-training"}]}},
            {"name": "model-training", "container": {"image": "i", "command": ["python", "-m", "train"],
                                                     "resources": {"requests": {"nvidia.com/gpu": 1}}}},
        ]},
    }


def test_results_go_to_the_apps_outputs_repository():
    ctx = yaml.safe_load(CTX_PATH.read_text())
    ctx["app"] = "myapp"
    out = enhance(_raw(), ctx)
    step = next(t for t in out["spec"]["templates"] if t["name"] == "model-training")
    env = {e["name"]: e.get("value") for e in step["container"]["env"]}
    assert env["CHECKPOINT_BUCKET"] == "outputs-myapp"
    assert env["CHECKPOINT_PREFIX"] == "main/checkpoints"
    assert env["KUBECORE_RUN_ID"] == "{{workflow.name}}"
    assert env["KUBECORE_WORKFLOW_NAME"] == "{{workflow.name}}", "names the MLflow run"
    mr = next(t for t in out["spec"]["templates"] if t["name"] == "hpc-follower")
    menv = {e["name"]: e.get("value") for e in mr["container"]["env"]}
    assert menv["DATASET"] == "{{workflow.parameters.dataset}}"
    assert menv["OUTPUTS_REPO"] == "outputs-myapp" and menv["OUTPUTS_REF"] == "main"
    assert "DATASET_REPO" not in menv and "OUTPUTS_BRANCH" not in menv


def test_compose_gets_the_outputs_repository_as_platform_checkpoints():
    ctx = yaml.safe_load(CTX_PATH.read_text())
    ctx["app"] = "myapp"
    raw = _raw()
    raw["spec"]["templates"].append({"name": "compose-and-validate", "container": {"image": "i", "args": []}})
    out = enhance(raw, ctx)
    args = next(t for t in out["spec"]["templates"] if t["name"] == "compose-and-validate")["container"]["args"]
    assert "platform.checkpoints.bucket=outputs-myapp" in args
    assert "platform.checkpoints.prefix=main/checkpoints" in args


def test_a_pipeline_without_a_dataset_parameter_runs_data_less_on_hpc():
    ctx = yaml.safe_load(CTX_PATH.read_text())
    raw = _raw()
    raw["spec"]["arguments"]["parameters"] = []
    mr = next(t for t in enhance(raw, ctx)["spec"]["templates"] if t["name"] == "hpc-follower")
    assert {e["name"]: e.get("value") for e in mr["container"]["env"]}["DATASET"] == ""
