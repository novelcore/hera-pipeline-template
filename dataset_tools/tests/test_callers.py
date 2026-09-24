"""The entry points outside dataset_cli must hand lakeFS the right credential.

login() returns a Credential (bearer token, or a cookie on the paste fallback).
In the YOLO template scripts/upload-dataset.py once passed that object
positionally as the *cookie*, so every upload failed auth. Pinned here.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

from dataset_cli.login import Credential

ROOT = pathlib.Path(__file__).resolve().parents[2]


class _Client:
    seen: dict = {}

    def __init__(self, url, cookie=None, concurrency=16, timeout=300, token=None):
        _Client.seen = {"url": url, "cookie": cookie, "token": token}

    def check_auth(self):
        return True

    def branch_exists(self, repo, branch):
        return True


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_upload_dataset_script_sends_bearer(monkeypatch, tmp_path):
    mod = _load(ROOT / "scripts" / "upload-dataset.py", "upload_dataset_script")
    monkeypatch.setattr(mod, "LakeFSClient", _Client)
    monkeypatch.setattr(mod, "do_login", lambda url: Credential(token="tok"))
    monkeypatch.setattr(mod, "do_sync", lambda *a, **k: "commit")

    class _Ok:
        ok, errors = True, []

    monkeypatch.setattr(mod, "validate_dataset", lambda d: _Ok())
    monkeypatch.setattr(sys, "argv", ["upload-dataset.py", str(tmp_path), "toy",
                                      "--url", "https://lakefs.example", "--repo", "r"])
    assert mod.main() == 0
    assert _Client.seen["token"] == "tok" and _Client.seen["cookie"] is None
