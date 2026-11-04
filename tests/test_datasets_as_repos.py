"""Platform side of datasets as repositories (PRD novelcore/kaos#1283 F-07).

These files are pinned by the platform CI for EVERY ML app: a run picks
`<dataset-repo>@<version>` (the `dataset` parameter), the MeluXina stage-in reads
the commit the run pinned, and every result goes to `outputs-<app>` on `main`.
"""
import io
import json
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kaos_pipeline.enhance import enhance  # noqa: E402
from kaos_pipeline.meluxina import MELUXINA_SUBMIT_CODE  # noqa: E402

CTX_PATH = ROOT / "kaos_pipeline/local-dev/pipeline-context.yaml"


def _submit_globals(monkeypatch, step_command, **env):
    base = {"SLURM_TOKEN": "t", "WF_UID": "u", "STEP_NAME": "s", "IMAGE_REF": "r/x:t",
            "STEP_COMMAND": json.dumps(step_command)}
    for k, v in {**base, **env}.items():
        monkeypatch.setenv(k, v)
    g = {}
    exec(MELUXINA_SUBMIT_CODE.split("jid = None")[0], g)
    return g


# ---------------------------------------------------------------- pinned commit

def test_hpc_pins_the_dataset_commit_an_upstream_step_recorded(monkeypatch):
    info = json.dumps({"dataset_commit": "c0ffee", "dataset": "dataset-x@v1"})
    g = _submit_globals(monkeypatch, ["python", "-m", "train", "--dataset-info", info])
    assert g["pinned_commit"]() == "c0ffee"


def test_hpc_without_a_recorded_commit_pins_nothing(monkeypatch):
    g = _submit_globals(monkeypatch, ["python", "-m", "train", "--dataset-info", "{}", "--x", "plain"])
    assert g["pinned_commit"]() == ""


def test_dataset_parameter_is_parsed_into_repo_and_ref(monkeypatch):
    g = _submit_globals(monkeypatch, ["x"], DATASET="dataset-cars@v2")
    assert g["dataset_coords"]() == ("dataset-cars", "v2")
    monkeypatch.setenv("DATASET", "dataset-cars@latest")
    assert g["dataset_coords"]() == ("dataset-cars", "main")
    monkeypatch.setenv("DATASET", "")
    assert g["dataset_coords"]() == ("", "")


def test_a_malformed_dataset_parameter_stops_the_submit(monkeypatch):
    g = _submit_globals(monkeypatch, ["x"], DATASET="main")
    try:
        g["dataset_coords"]()
        raise AssertionError("must exit")
    except SystemExit as exc:
        assert exc.code == 1


# ---------------------------------------------------------------- stage-in / stage-out

class _LakeFS:
    """urlopen stand-in for the lakeFS objects API the stage-in/out scripts use."""

    def __init__(self, objects):
        self.objects, self.urls = objects, []

    def __call__(self, req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        self.urls.append(url)
        if "/commits" in url:
            return io.BytesIO(json.dumps({"results": [{"id": "tipcommit"}]}).encode())
        if "/objects/ls?" in url:
            q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
            prefix = urllib.request.unquote(q.get("prefix", ""))
            res = [{"path": p, "path_type": "object", "size_bytes": len(b)}
                   for p, b in self.objects.items() if p.startswith(prefix)]
            return io.BytesIO(json.dumps({"results": res, "pagination": {"has_more": False}}).encode())
        if "/objects?" in url:
            path = urllib.request.unquote(url.split("path=", 1)[1])
            return io.BytesIO(self.objects.get(path, b""))
        return io.BytesIO(b"{}")


def _stagein_env(monkeypatch, tmp_path, **extra):
    for k, v in {"LAKEFS_ENDPOINT": "https://lakefs.example", "LAKEFS_BEARER_TOKEN": "jwt",
                 "DATASET_REPO": "dataset-cars", "DATASET_REF": "v1",
                 "DATASET_CACHE": str(tmp_path / "cache"),
                 "DATASET_DIRFILE": str(tmp_path / "dir"), **extra}.items():
        monkeypatch.setenv(k, v)


def _stagein_code():
    g = {}
    exec(MELUXINA_SUBMIT_CODE.split("API = ")[0], g)
    return g["STAGEIN"]


def test_stage_in_downloads_only_the_dataset_at_the_pinned_commit(tmp_path, monkeypatch):
    lakefs = _LakeFS({"data.yaml": b"y", "images/train/a.jpg": b"img", "labels/train/a.txt": b"0",
                      "README.md": b"notes"})
    monkeypatch.setattr(urllib.request, "urlopen", lakefs)
    _stagein_env(monkeypatch, tmp_path, DATASET_COMMIT="c0ffee")
    exec(_stagein_code(), {})
    dest = tmp_path / "cache" / "dataset-cars" / "c0ffee"
    assert (dest / "data.yaml").read_bytes() == b"y"
    assert (dest / "images/train/a.jpg").exists() and not (dest / "README.md").exists()
    assert (dest / ".kaos-commit").read_text() == "c0ffee", "the kaos-lib consumer finds the commit here"
    assert not any("/commits" in u for u in lakefs.urls), "a pinned commit is never re-resolved"


def test_stage_in_without_a_pin_resolves_the_ref(tmp_path, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _LakeFS({"data.yaml": b"y"}))
    _stagein_env(monkeypatch, tmp_path)
    monkeypatch.delenv("DATASET_COMMIT", raising=False)
    exec(_stagein_code(), {})
    assert (tmp_path / "cache" / "dataset-cars" / "tipcommit" / "data.yaml").exists()


def test_stage_out_goes_to_a_hand_off_branch_of_the_outputs_repository(tmp_path, monkeypatch):
    lakefs = _LakeFS({})
    monkeypatch.setattr(urllib.request, "urlopen", lakefs)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "training-result.json").write_text("{}")
    for k, v in {"LAKEFS_ENDPOINT": "https://lakefs.example", "LAKEFS_BEARER_TOKEN": "jwt",
                 "OUTPUTS_REPO": "outputs-myapp", "OUTPUTS_REF": "main",
                 "WF_UID": "u", "STEP_NAME": "model-training", "STEP_OUTPUTS": "training-result",
                 "KAOS_WORK": str(tmp_path)}.items():
        monkeypatch.setenv(k, v)
    g = {}
    exec(MELUXINA_SUBMIT_CODE.split("import base64, json")[0], g)
    exec(g["STAGEOUT"], {})
    # a hand-off branch, never main: a merge into a dirty main is refused by lakeFS
    assert any("/repositories/outputs-myapp/branches/hpc-u-model-training/objects?" in u for u in lakefs.urls), lakefs.urls
    assert not any("/branches/main/objects" in u for u in lakefs.urls)


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
    assert env["KAOS_RUN_ID"] == "{{workflow.name}}"
    assert env["KAOS_WORKFLOW_NAME"] == "{{workflow.name}}", "names the MLflow run"
    assert env["KUBECORE_RUN_ID"] == "{{workflow.name}}", "deprecated alias, older kaos-lib reads it"
    assert env["KUBECORE_WORKFLOW_NAME"] == "{{workflow.name}}", "deprecated alias"
    mr = next(t for t in out["spec"]["templates"] if t["name"] == "meluxina-run")
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
    mr = next(t for t in enhance(raw, ctx)["spec"]["templates"] if t["name"] == "meluxina-run")
    assert {e["name"]: e.get("value") for e in mr["container"]["env"]}["DATASET"] == ""


def test_slurm_env_omits_unset_checkpoint_settings():
    """Step code reads os.environ.get(KEY, default): an empty value would beat its default."""
    assert "'CHECKPOINT_BUCKET=' +" not in MELUXINA_SUBMIT_CODE
    assert "if os.environ.get(k)]" in MELUXINA_SUBMIT_CODE
