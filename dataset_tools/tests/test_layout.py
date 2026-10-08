"""Every upload path must land where the pipeline reads, and never delete silently.

The pipeline (config-validation + dataset-loading) reads exactly
``s3://<repo>/<data-ref>/dataset/<data-version>/``, data-version defaulting to
data-ref. Before this was pinned, the three entry points wrote three different
places — ``scripts/upload-dataset.py`` to ``<ref>/dataset/``, ``kubecore-dataset
sync`` and the env shim to the branch root — so an upload "succeeded" and the
run then failed with "dataset path not found or empty".
"""
from __future__ import annotations

import importlib.util
import io
import pathlib
import sys

import pytest

from dataset_cli import __main__ as cli
from dataset_cli import sync as sync_mod
from dataset_cli.login import Credential

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Client:
    def __init__(self, *a, **k):
        pass

    def branch_exists(self, repo, branch):
        return True


def _capture_sync(monkeypatch, mod):
    seen = {}

    def fake_sync(root, client, repo, branch, **kw):
        seen.update(repo=repo, branch=branch, **kw)
        return "commit"

    monkeypatch.setattr(mod, "do_sync", fake_sync)
    monkeypatch.setattr(mod, "LakeFSClient", _Client)
    monkeypatch.setattr(mod, "do_login", lambda *a, **k: Credential(token="t"))
    return seen


def test_standard_prefix():
    assert sync_mod.dataset_prefix("main") == "dataset/main"
    assert sync_mod.dataset_prefix("/v2/") == "dataset/v2"


# --- scripts/upload-dataset.py (the command the docs tell people to use) ---

@pytest.fixture
def wrapper(tmp_path):
    # This template's script takes any folder of files (no dataset format check).
    (tmp_path / "data.csv").write_text("a,b\n")
    return _load(ROOT / "scripts" / "upload-dataset.py", "upload_dataset_script")


def test_wrapper_refuses_an_empty_folder(monkeypatch, tmp_path):
    mod = _load(ROOT / "scripts" / "upload-dataset.py", "upload_dataset_script")
    seen = _capture_sync(monkeypatch, mod)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _run_wrapper(monkeypatch, mod, empty) == 2
    assert seen == {}


def _run_wrapper(monkeypatch, mod, tmp_path, *extra):
    monkeypatch.setattr(sys, "argv", ["upload-dataset.py", str(tmp_path), *extra,
                                      "--url", "https://lakefs.example", "--repo", "r"])
    return mod.main()


def test_wrapper_default_lands_on_the_default_run_path(monkeypatch, wrapper, tmp_path):
    seen = _capture_sync(monkeypatch, wrapper)
    assert _run_wrapper(monkeypatch, wrapper, tmp_path) == 0
    # default run reads main/dataset/main/
    assert (seen["branch"], seen["prefix"]) == ("main", "dataset/main")
    assert seen["confirm_deletes"] is True


def test_wrapper_name_is_the_data_ref(monkeypatch, wrapper, tmp_path):
    """The second argument names the dataset (= data-ref), so a new name never
    touches another dataset — it used to be an MLflow tag while the files went to
    main regardless."""
    seen = _capture_sync(monkeypatch, wrapper)
    _run_wrapper(monkeypatch, wrapper, tmp_path, "cats")
    assert (seen["branch"], seen["prefix"]) == ("cats", "dataset/cats")


def test_wrapper_data_version(monkeypatch, wrapper, tmp_path):
    seen = _capture_sync(monkeypatch, wrapper)
    _run_wrapper(monkeypatch, wrapper, tmp_path, "cats", "--data-version", "v2")
    assert (seen["branch"], seen["prefix"]) == ("cats", "dataset/v2")


def test_wrapper_yes_skips_the_delete_prompt(monkeypatch, wrapper, tmp_path):
    seen = _capture_sync(monkeypatch, wrapper)
    _run_wrapper(monkeypatch, wrapper, tmp_path, "cats", "--yes")
    assert seen["confirm_deletes"] is False


# --- kubecore-dataset sync / upload ---

def test_cli_sync_lands_on_the_standard_path(monkeypatch, tmp_path):
    seen = _capture_sync(monkeypatch, cli)
    monkeypatch.setattr(cli, "validate_dataset", lambda d: type("R", (), {"ok": True, "report": lambda s: ""})())
    cli.main(["sync", str(tmp_path), "--url", "https://lakefs.example", "--repo", "r",
              "--branch", "cats"])
    assert (seen["branch"], seen["prefix"]) == ("cats", "dataset/cats")
    assert seen["confirm_deletes"] is True


# --- deprecated env shim ---

def test_env_shim_lands_on_the_standard_path(monkeypatch, tmp_path):
    mod = _load(ROOT / "dataset_tools" / "upload_to_lakefs_api.py", "upload_to_lakefs_api")
    seen = _capture_sync(monkeypatch, mod)
    for k, v in {"LAKEFS_URL": "https://lakefs.example", "LAKEFS_REPO": "r",
                 "LAKEFS_BRANCH": "cats", "LOCAL_DIR": str(tmp_path)}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("LAKEFS_COOKIE", raising=False)
    monkeypatch.delenv("UPLOAD_PREFIX", raising=False)
    mod.main()
    assert (seen["branch"], seen["prefix"]) == ("cats", "dataset/cats")


# --- the delete guard itself ---

class _WriteClient:
    def __init__(self):
        self.writes = []

    def upload_object(self, *a):
        self.writes.append(("up", a))

    def delete_object(self, *a):
        self.writes.append(("del", a))

    def commit(self, *a):
        return "c"


def _plan_with_deletes(monkeypatch, tmp_path):
    plan = sync_mod.SyncPlan(add=[(tmp_path / "x", "dataset/main/x")],
                             delete=["dataset/main/old.png"])
    monkeypatch.setattr(sync_mod, "plan_sync", lambda *a, **k: plan)


def test_guard_refuses_without_a_terminal(monkeypatch, tmp_path):
    _plan_with_deletes(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))  # not a tty
    client = _WriteClient()
    with pytest.raises(SystemExit, match="--yes"):
        sync_mod.sync(tmp_path, client, "r", "main", prefix="dataset/main", confirm_deletes=True)
    assert client.writes == [], "must not upload or delete anything before confirmation"


def test_guard_no_answer_aborts(monkeypatch, tmp_path):
    _plan_with_deletes(monkeypatch, tmp_path)
    tty = io.StringIO("n\n")
    tty.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", tty)
    client = _WriteClient()
    with pytest.raises(SystemExit, match="Aborted"):
        sync_mod.sync(tmp_path, client, "r", "main", prefix="dataset/main", confirm_deletes=True)
    assert client.writes == []


def test_guard_yes_answer_proceeds(monkeypatch, tmp_path):
    _plan_with_deletes(monkeypatch, tmp_path)
    tty = io.StringIO("y\n")
    tty.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", tty)
    client = _WriteClient()
    assert sync_mod.sync(tmp_path, client, "r", "main", prefix="dataset/main",
                         confirm_deletes=True, concurrency=1) == "c"
    assert ("del", ("r", "main", "dataset/main/old.png")) in client.writes


def test_unreachable_lakefs_is_one_readable_line(monkeypatch, tmp_path):
    """A wrong link or no network used to dump a ~100-line urllib3 traceback."""
    import requests

    def boom(*a, **k):
        req = requests.Request("GET", "https://lakefs-gone.example/api/v1/repositories").prepare()
        raise requests.exceptions.ConnectionError("Name or service not known", request=req)

    monkeypatch.setattr(cli, "do_login", boom)
    monkeypatch.setattr(cli, "validate_dataset", lambda d: type("R", (), {"ok": True, "report": lambda s: ""})())
    with pytest.raises(SystemExit) as exc:
        cli.main(["sync", str(tmp_path), "--url", "https://lakefs-gone.example", "--repo", "r"])
    msg = str(exc.value)
    assert msg.startswith("ERROR: cannot reach lakefs-gone.example")
    assert "\n" not in msg


def test_sync_never_sees_a_name_prefixed_sibling(tmp_path):
    """dataset/main must not list, and so never plan to delete, dataset/main2/."""
    seen = []

    class _Remote:
        def list_objects(self, repo, ref, prefix=""):
            seen.append(prefix)
            for path in ("dataset/main/old.png", "dataset/main2/keep.png"):
                if path.startswith(prefix):
                    yield {"path": path, "checksum": "x"}

    (tmp_path / "data.yaml").write_text("path: .\n")
    plan = sync_mod.plan_sync(tmp_path, _Remote(), "r", "main", "dataset/main")
    assert seen == ["dataset/main/"]
    assert plan.delete == ["dataset/main/old.png"]
