"""The entry points outside dataset_cli must hand lakeFS the right credential.

login() returns a Credential (bearer token, or a cookie on the paste fallback).
Before this was pinned, both upload_to_lakefs_api.py and scripts/upload-dataset.py
passed that object positionally as the *cookie* — every upload through them
would have sent a stringified Credential and failed auth.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

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


def test_upload_to_lakefs_api_sends_bearer(monkeypatch, tmp_path):
    mod = _load(ROOT / "dataset_tools" / "upload_to_lakefs_api.py", "upload_to_lakefs_api")
    monkeypatch.setattr(mod, "LakeFSClient", _Client)
    monkeypatch.setattr(mod, "do_login", lambda url: Credential(token="tok"))
    monkeypatch.setattr(mod, "do_sync", lambda *a, **k: "commit")
    for k, v in {"LAKEFS_URL": "https://lakefs.example", "LAKEFS_REPO": "r",
                 "LOCAL_DIR": str(tmp_path)}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("LAKEFS_COOKIE", raising=False)

    mod.main()
    assert _Client.seen == {"url": "https://lakefs.example", "cookie": None, "token": "tok"}


def test_upload_to_lakefs_api_explicit_cookie_still_works(monkeypatch, tmp_path):
    mod = _load(ROOT / "dataset_tools" / "upload_to_lakefs_api.py", "upload_to_lakefs_api")
    monkeypatch.setattr(mod, "LakeFSClient", _Client)
    monkeypatch.setattr(mod, "save_session", lambda *a, **k: None)
    monkeypatch.setattr(mod, "do_login", lambda url: pytest.fail("logged in despite LAKEFS_COOKIE"))
    monkeypatch.setattr(mod, "do_sync", lambda *a, **k: "commit")
    for k, v in {"LAKEFS_URL": "https://lakefs.example", "LAKEFS_REPO": "r",
                 "LOCAL_DIR": str(tmp_path), "LAKEFS_COOKIE": "c00kie"}.items():
        monkeypatch.setenv(k, v)

    mod.main()
    assert _Client.seen["cookie"] == "c00kie" and _Client.seen["token"] is None


def test_upload_dataset_script_sends_bearer(monkeypatch, tmp_path):
    mod = _load(ROOT / "scripts" / "upload-dataset.py", "upload_dataset_script")
    monkeypatch.setattr(mod, "LakeFSClient", _Client)
    monkeypatch.setattr(mod, "do_login", lambda url: Credential(token="tok"))
    monkeypatch.setattr(mod, "do_sync", lambda *a, **k: "commit")

    (tmp_path / "data.csv").write_text("a,b\n")
    monkeypatch.setattr(sys, "argv", ["upload-dataset.py", str(tmp_path), "toy",
                                      "--url", "https://lakefs.example", "--repo", "r"])
    assert mod.main() == 0
    assert _Client.seen["token"] == "tok" and _Client.seen["cookie"] is None
