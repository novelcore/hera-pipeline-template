"""PRD-HPC-1541 F-03/F-06: the MeluXina twin stages the pinned dataset commit
from a login node before it submits, and the job binds the resident copy.

The stager itself (kubecore-operator images/meluxina-tokenmint/stager) is
tested in the operator repo; here it is a stand-in that records what the twin
asks for and streams, against a fake lakeFS.
Run:  python -m pytest tests/ -v
"""
import io
import json
import os
import stat
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kubecore.enhance import enhance  # noqa: E402
from kubecore.meluxina import MELUXINA_SUBMIT_CODE  # noqa: E402

CTX_PATH = ROOT / "kubecore/local-dev/pipeline-context.yaml"
COMMIT = "c2" * 32
BASE = "c1" * 32


class _LakeFS:
    """urlopen stand-in: objects/ls and a two-dot diff."""

    def __init__(self, objects, diff=()):
        self.objects, self.diff, self.urls = objects, list(diff), []

    def __call__(self, req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        self.urls.append(url)
        q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        prefix = urllib.request.unquote(q.get("prefix", ""))
        if "/diff/" in url:
            res = [dict(d, path_type="object") for d in self.diff if d["path"].startswith(prefix)]
        else:
            res = [{"path": p, "path_type": "object", "size_bytes": n}
                   for p, n in self.objects.items() if p.startswith(prefix)]
        return io.BytesIO(json.dumps({"results": res, "pagination": {"has_more": False}}).encode())


class _Stager:
    """Stand-in for the login-node stager: canned status, records stage calls."""

    def __init__(self, status, stage_rcs=(0,)):
        self.status, self.stage_rcs, self.calls = status, list(stage_rcs), []

    def __call__(self, words, feed=None):
        records = list(feed) if feed is not None else None
        self.calls.append((words, records))
        if words[0] == "status":
            return 0, [dict(self.status, event="status", path="/scr/kaos/p/datasets/ds/" + COMMIT)]
        rc = self.stage_rcs.pop(0)
        return rc, ([{"event": "done", "path": "/scr/kaos/p/datasets/ds/" + COMMIT}] if rc == 0 else [])


def _twin(monkeypatch, tmp_path, lakefs, stager, key=True):
    summary = json.dumps({"commit": COMMIT, "ref": "main"})
    for k, v in {"SLURM_TOKEN": "t", "WF_UID": "u", "STEP_NAME": "s", "IMAGE_REF": "r/x:t",
                 "STEP_COMMAND": json.dumps(["python", "-m", "train", "--manifest-summary", summary]),
                 "DATASET_REPO": "poulaki", "DATASET_REF": "main",
                 "LAKEFS_EXTERNAL_URL": "https://lakefs.example/",
                 "HPC_USER": "u1", "HPC_ACCOUNT": "p1", "HPC_SCRATCH": "/s", "HPC_HOME": "/h"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(urllib.request, "urlopen", lakefs)
    g = {}
    exec(MELUXINA_SUBMIT_CODE.split("jid = None")[0], g)
    if key:
        (tmp_path / "id_ed25519").write_text("k")
    g.update(STAGING_DIR=str(tmp_path), mint_wallet=lambda: "wallet-jwt")
    if stager is not None:
        g["stager"] = stager
    monkeypatch.setattr(g["subprocess"], "call", lambda *a, **kw: 0)   # ssh client present
    monkeypatch.setattr(g["time"], "sleep", lambda s: None)
    return g


def _stage_call(stager):
    return next((w, r) for w, r in stager.calls if w[0] == "stage")


def test_first_copy_streams_every_dataset_object(monkeypatch, tmp_path):
    lakefs = _LakeFS({"dataset/data.yaml": 4, "dataset/images/a.jpg": 10, "checkpoints/x.pt": 99})
    stager = _Stager({"ready": False, "base": None})
    g = _twin(monkeypatch, tmp_path, lakefs, stager)
    assert g["stage_dataset"]().endswith(COMMIT)
    words, records = _stage_call(stager)
    assert "--base" not in words
    assert words[words.index("--need-bytes") + 1] == 14 and words[words.index("--need-files") + 1] == 2
    assert records[0] == {"op": "auth", "authorization": "Bearer wallet-jwt"}
    fetched = {r["path"]: r for r in records if r["op"] == "fetch"}
    assert set(fetched) == {"dataset/data.yaml", "dataset/images/a.jpg"}, "only the dataset"
    assert fetched["dataset/images/a.jpg"]["url"] == (
        "https://lakefs.example/api/v1/repositories/poulaki/refs/%s/objects?path=dataset%%2Fimages%%2Fa.jpg"
        % COMMIT)
    assert records[-1] == {"op": "end", "files": 2, "bytes": 14, "ref": "main", "prefix": "dataset/"}


def test_delta_lists_only_the_two_dot_diff_against_the_base(monkeypatch, tmp_path):
    lakefs = _LakeFS({"dataset/a.jpg": 1}, diff=[
        {"type": "added", "path": "dataset/new.jpg", "size_bytes": 5},
        {"type": "changed", "path": "dataset/a.jpg", "size_bytes": 7},
        {"type": "removed", "path": "dataset/gone.jpg", "size_bytes": 3}])
    stager = _Stager({"ready": False, "base": BASE, "base_files": 10, "base_prefix": "dataset/"})
    g = _twin(monkeypatch, tmp_path, lakefs, stager)
    assert g["stage_dataset"]()
    words, records = _stage_call(stager)
    assert words[words.index("--base") + 1] == BASE
    assert words[words.index("--need-files") + 1] == 2 and words[words.index("--need-bytes") + 1] == 12
    assert {"op": "delete", "path": "dataset/gone.jpg"} in records
    assert records[-1]["files"] == 10 + 1 - 1, "base count + added - removed"
    assert any("/refs/%s/diff/%s?" % (BASE, COMMIT) in u and "type=two_dot" in u for u in lakefs.urls)
    assert not any("/objects/ls?" in u and "prefix=dataset%2F&" not in u for u in lakefs.urls)


def test_a_base_with_another_layout_is_not_used(monkeypatch, tmp_path):
    lakefs = _LakeFS({"dataset/a.jpg": 1})
    stager = _Stager({"ready": False, "base": BASE, "base_files": 10, "base_prefix": ""})
    g = _twin(monkeypatch, tmp_path, lakefs, stager)
    assert g["stage_dataset"]()
    assert "--base" not in _stage_call(stager)[0]


def test_a_ready_copy_is_never_listed_again(monkeypatch, tmp_path):
    lakefs = _LakeFS({"dataset/a.jpg": 1})
    stager = _Stager({"ready": True})
    g = _twin(monkeypatch, tmp_path, lakefs, stager)
    assert g["stage_dataset"]().endswith(COMMIT)
    assert lakefs.urls == [] and [w[0] for w, _ in stager.calls] == ["status"]


def test_retry_resumes_and_no_space_gives_up(monkeypatch, tmp_path):
    lakefs = _LakeFS({"dataset/a.jpg": 1})
    stager = _Stager({"ready": False, "base": None}, stage_rcs=[75, 0])
    g = _twin(monkeypatch, tmp_path, lakefs, stager)
    assert g["stage_dataset"](), "exit 75 (dropped session, busy lock) is retried"
    stager = _Stager({"ready": False, "base": None}, stage_rcs=[76, 0])
    g = _twin(monkeypatch, tmp_path, lakefs, stager)
    assert g["stage_dataset"]() == "", "no space is not retried: the job stages in-job"
    assert sum(w[0] == "stage" for w, _ in stager.calls) == 1


def test_without_the_staging_key_the_job_stages_in_job(monkeypatch, tmp_path):
    stager = _Stager({"ready": True})
    g = _twin(monkeypatch, tmp_path, _LakeFS({}), stager, key=False)
    assert g["stage_dataset"]() == "" and stager.calls == []


def test_a_failed_feed_ends_the_stream_without_an_end_record(monkeypatch, tmp_path):
    """The real stager() helper: a lakeFS error mid-listing closes stdin with no
    end record (the stager keeps resumable state) and surfaces the error."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ssh = bindir / "ssh"
    ssh.write_text('#!/bin/sh\nn=$(wc -l)\necho "{\\"event\\": \\"got\\", \\"lines\\": $n}"\nexit 75\n')
    ssh.chmod(ssh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    g = _twin(monkeypatch, tmp_path, _LakeFS({}), None)

    def feed():
        yield {"op": "auth", "authorization": "Bearer x"}
        yield {"op": "fetch", "path": "a", "size": 1, "url": "u"}
        raise IOError("lakeFS 502")
    try:
        g["stager"](["stage", "--repo", "poulaki"], feed())
        raise AssertionError("the feed error must surface")
    except IOError:
        pass
    rc, events = g["stager"](["status"], iter([{"op": "end"}]))
    assert rc == 75 and events == [{"event": "got", "lines": 1}]


def test_job_binds_the_resident_copy_and_leases_the_commit():
    src = MELUXINA_SUBMIT_CODE
    assert '[ -f "$DATASET_STAGED/.kaos-ready" ]' in src
    assert "'DATASET_STAGED=' + STAGED" in src
    assert "body['job']['comment'] = 'kaos-commit=' + commit" in src


def test_twin_mounts_the_staging_key_read_only():
    raw = {"apiVersion": "argoproj.io/v1alpha1", "kind": "WorkflowTemplate", "metadata": {"name": "x"},
           "spec": {"entrypoint": "p", "arguments": {"parameters": []}, "templates": [
               {"name": "p", "dag": {"tasks": [{"name": "model-training", "template": "model-training"}]}},
               {"name": "model-training", "container": {"image": "i", "command": ["python"],
                                                        "resources": {"requests": {"nvidia.com/gpu": 1}}}}]}}
    out = enhance(raw, yaml.safe_load(CTX_PATH.read_text()))
    mr = next(t for t in out["spec"]["templates"] if t["name"] == "meluxina-run")
    vol = next(v for v in mr["volumes"] if v["name"] == "meluxina-staging")
    assert vol["secret"] == {"secretName": "meluxina-staging", "defaultMode": 0o400, "optional": True}
    assert {"name": "meluxina-staging", "mountPath": "/etc/meluxina-staging", "readOnly": True} \
        in mr["container"]["volumeMounts"]
