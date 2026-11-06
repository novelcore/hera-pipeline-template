"""The job's image-pull credential: a 12 h read-only token, not the pod's 1 h CI token.

The waiter mints it by impersonating the org's read-only pull GSA (<org>-hpc-pull, published
by the operator as pipeline-context hpc.pullServiceAccount). Any failure falls back to the
pod's own metadata token, and never fails the submit.
Run:  python -m pytest tests/ -v
"""
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kubecore import meluxina  # noqa: E402
from kubecore.meluxina import MELUXINA_SUBMIT_CODE  # noqa: E402

SA = "kaos-io-hpc-pull@kaos-dev-511509.iam.gserviceaccount.com"
IAM = ("https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/%s:generateAccessToken" % SA)


class _Resp(io.BytesIO):
    pass


def _runner(monkeypatch, urlopen, pull_sa=SA):
    monkeypatch.delenv("HPC_PULL_SA", raising=False)
    if pull_sa:
        monkeypatch.setenv("HPC_PULL_SA", pull_sa)
    for k, v in {"SLURM_TOKEN": "t", "WF_UID": "u", "STEP_NAME": "s", "IMAGE_REF": "r/x:t",
                 "STEP_COMMAND": "[]"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    g = {}
    exec(MELUXINA_SUBMIT_CODE.split("def submit():")[0], g)
    return g["pull_token"]


def _fake(calls, iam):
    def urlopen(req, timeout=None):
        calls.append(req)
        if "metadata.google.internal" in req.full_url:
            return _Resp(json.dumps({"access_token": "pod-1h"}).encode())
        return iam(req)
    return urlopen


def test_mints_twelve_hours_as_the_pull_gsa_authenticated_by_the_pod_token(monkeypatch):
    calls = []
    pull_token = _runner(monkeypatch, _fake(calls, lambda r: _Resp(b'{"accessToken": "pull-12h"}')))
    assert pull_token() == "pull-12h"
    iam = calls[1]
    assert iam.full_url == IAM
    assert iam.get_header("Authorization") == "Bearer pod-1h"
    body = json.loads(iam.data)
    assert body["lifetime"] == "43200s"
    assert body["scope"] == ["https://www.googleapis.com/auth/cloud-platform"]


def test_without_a_pull_gsa_the_pods_own_token_is_used_and_iam_is_not_called(monkeypatch):
    calls = []
    pull_token = _runner(monkeypatch, _fake(calls, lambda r: (_ for _ in ()).throw(AssertionError("iam"))),
                         pull_sa="")
    assert pull_token() == "pod-1h"
    assert len(calls) == 1


def test_policy_or_permission_denied_falls_back_to_the_pod_token(monkeypatch, capsys):
    def deny(req):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"error":"lifetime"}'))
    pull_token = _runner(monkeypatch, _fake([], deny))
    assert pull_token() == "pod-1h"
    out = capsys.readouterr().out
    assert "unavailable" in out and "HTTP 403" in out and "lifetime" in out


def test_network_error_and_empty_response_fall_back(monkeypatch):
    def boom(req):
        raise OSError("no route")
    assert _runner(monkeypatch, _fake([], boom))() == "pod-1h"
    assert _runner(monkeypatch, _fake([], lambda r: _Resp(b"{}")))() == "pod-1h"


def test_no_metadata_server_is_still_anonymous_pull(monkeypatch):
    def urlopen(req, timeout=None):
        raise OSError("no metadata")
    assert _runner(monkeypatch, urlopen)() == ""


def test_the_operators_pull_gsa_reaches_the_waiter_env():
    assert meluxina.pull_env({}) == [] and meluxina.pull_env({"hpc": {}}) == []
    assert meluxina.pull_env({"hpc": {"pullServiceAccount": SA}}) == [{"name": "HPC_PULL_SA", "value": SA}]
