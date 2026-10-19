"""Platform side of datasets as lakeFS branches (yolo-pipelines-template#33).

These files are pinned by the platform CI for EVERY ML app: the MeluXina
stage-in reads the commit the app's dataset-loading pinned (or resolves the
ref for older step code), stages only dataset/ (the whole ref for data from
before that layout), and pipeline outputs go to the project's `outputs`
branch once it exists.
"""
import io
import json
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kubecore.enhance import enhance  # noqa: E402
from kubecore.meluxina import MELUXINA_SUBMIT_CODE  # noqa: E402

CTX_PATH = ROOT / "kubecore/local-dev/pipeline-context.yaml"


# ---------------------------------------------------------------- MeluXina

def _submit_globals(monkeypatch, step_command):
    for k, v in {"SLURM_TOKEN": "t", "WF_UID": "u", "STEP_NAME": "s", "IMAGE_REF": "r/x:t",
                 "STEP_COMMAND": json.dumps(step_command)}.items():
        monkeypatch.setenv(k, v)
    g = {}
    exec(MELUXINA_SUBMIT_CODE.split("jid = None")[0], g)
    return g


def test_hpc_pins_the_commit_dataset_loading_resolved(monkeypatch):
    summary = json.dumps({"bucket": "poulaki", "prefix": "c0ffee/dataset/", "commit": "c0ffee"})
    g = _submit_globals(monkeypatch, ["python", "-m", "train", "--manifest-summary", summary])
    assert g["pinned_commit"]() == "c0ffee"


def test_hpc_pins_the_commit_training_used(monkeypatch):
    tr = json.dumps({"best_checkpoint_s3": "s3://x", "dataset_commit": "c0ffee"})
    g = _submit_globals(monkeypatch, ["python", "-m", "qat", "--training-result", tr])
    assert g["pinned_commit"]() == "c0ffee"


def test_hpc_without_a_pinned_commit_resolves_the_ref(monkeypatch):
    g = _submit_globals(monkeypatch, ["python", "-m", "train", "--manifest-summary", "{}"])
    assert g["pinned_commit"]() == ""


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


def _stage_globals():
    g = {}
    exec(MELUXINA_SUBMIT_CODE.split("API = ")[0], g)
    return g


def test_stage_in_downloads_only_the_pinned_dataset(tmp_path, monkeypatch):
    lakefs = _LakeFS({"dataset/data.yaml": b"y", "dataset/images/a.jpg": b"img",
                      "checkpoints/old.pt": b"weights"})
    monkeypatch.setattr(urllib.request, "urlopen", lakefs)
    for k, v in {"LAKEFS_ENDPOINT": "https://lakefs.example", "LAKEFS_BEARER_TOKEN": "jwt",
                 "DATASET_REPO": "poulaki", "DATASET_REF": "cats", "DATASET_COMMIT": "c0ffee",
                 "DATASET_CACHE": str(tmp_path / "cache"),
                 "DATASET_DIRFILE": str(tmp_path / "dir")}.items():
        monkeypatch.setenv(k, v)
    exec(_stage_globals()["STAGEIN"], {})
    dest = tmp_path / "cache" / "poulaki" / "c0ffee"
    assert (dest / "dataset/data.yaml").read_bytes() == b"y"
    assert not (dest / "checkpoints").exists()
    assert not any("/commits" in u for u in lakefs.urls), "a pinned commit is never re-resolved"


def test_stage_in_takes_the_whole_ref_for_pre_layout_data(tmp_path, monkeypatch):
    lakefs = _LakeFS({"data.yaml": b"y", "images/a.jpg": b"img"})
    monkeypatch.setattr(urllib.request, "urlopen", lakefs)
    for k, v in {"LAKEFS_ENDPOINT": "https://lakefs.example", "LAKEFS_BEARER_TOKEN": "jwt",
                 "DATASET_REPO": "poulaki", "DATASET_REF": "cats",
                 "DATASET_CACHE": str(tmp_path / "cache"),
                 "DATASET_DIRFILE": str(tmp_path / "dir")}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("DATASET_COMMIT", raising=False)
    exec(_stage_globals()["STAGEIN"], {})
    assert (tmp_path / "cache" / "poulaki" / "tipcommit" / "data.yaml").exists()


def test_stage_out_goes_to_the_outputs_branch(tmp_path, monkeypatch):
    lakefs = _LakeFS({})
    monkeypatch.setattr(urllib.request, "urlopen", lakefs)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "training-result.json").write_text("{}")
    for k, v in {"LAKEFS_ENDPOINT": "https://lakefs.example", "LAKEFS_BEARER_TOKEN": "jwt",
                 "DATASET_REPO": "poulaki", "DATASET_REF": "cats", "OUTPUTS_BRANCH": "outputs",
                 "WF_UID": "u", "STEP_NAME": "model-training", "STEP_OUTPUTS": "training-result",
                 "KAOS_WORK": str(tmp_path)}.items():
        monkeypatch.setenv(k, v)
    g = {}
    exec(MELUXINA_SUBMIT_CODE.split("import base64, json")[0], g)
    exec(g["STAGEOUT"], {})
    assert any("/branches/outputs/objects?" in u for u in lakefs.urls), lakefs.urls


def _raw():
    return {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "WorkflowTemplate", "metadata": {"name": "x"},
        "spec": {"entrypoint": "p", "arguments": {"parameters": [{"name": "data-ref", "value": "main"}]},
                 "templates": [
            {"name": "p", "dag": {"tasks": [{"name": "model-training", "template": "model-training"}]}},
            {"name": "model-training", "container": {"image": "i", "command": ["python", "-m", "train"],
                                                     "resources": {"requests": {"nvidia.com/gpu": 1}}}},
        ]},
    }


def test_platform_wiring_follows_the_outputs_branch():
    ctx = yaml.safe_load(CTX_PATH.read_text())
    ctx["lakefs"]["outputsBranch"] = "outputs"
    ctx["checkpoints"] = {"bucket": "poulaki", "prefix": "outputs/checkpoints"}
    out = enhance(_raw(), ctx)
    step = next(t for t in out["spec"]["templates"] if t["name"] == "model-training")
    env = {e["name"]: e.get("value") for e in step["container"]["env"]}
    assert env["KUBECORE_RUN_ID"] == "{{workflow.name}}"
    assert env["CHECKPOINT_PREFIX"] == "outputs/checkpoints"
    mr = next(t for t in out["spec"]["templates"] if t["name"] == "meluxina-run")
    menv = {e["name"]: e.get("value") for e in mr["container"]["env"]}
    assert menv["OUTPUTS_BRANCH"] == "outputs"
    assert menv["CHECKPOINT_PREFIX"] == "outputs/checkpoints"
    assert menv["KUBECORE_RUN_ID"] == "{{workflow.name}}"


def test_no_outputs_branch_keeps_todays_hand_off():
    ctx = yaml.safe_load(CTX_PATH.read_text())
    ctx["lakefs"].pop("outputsBranch", None)
    mr = next(t for t in enhance(_raw(), ctx)["spec"]["templates"] if t["name"] == "meluxina-run")
    assert {e["name"]: e.get("value") for e in mr["container"]["env"]}["OUTPUTS_BRANCH"] == ""


def test_slurm_env_omits_unset_checkpoint_settings():
    """Step code reads os.environ.get(KEY, default): an empty value would beat
    its default (old code then uploaded to bucket '')."""
    src = MELUXINA_SUBMIT_CODE
    assert "'CHECKPOINT_BUCKET=' +" not in src
    assert "if os.environ.get(k)]" in src
