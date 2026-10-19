"""Every upload path must land where the pipeline reads, and never delete silently.

The pipeline (config-validation + dataset-loading) reads exactly
``s3://<repo>/<data-ref>/dataset/`` — the same path on every branch, so lakeFS can
branch, diff and merge datasets. Before this was pinned, the three entry points
wrote three different places, so an upload "succeeded" and the run then failed
with "dataset path not found or empty". A dataset in the older
``dataset/<data-version>/`` layout is still read by apps on older step code, so
a sync never deletes it unless asked.
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


class _NewBranchClient:
    """lakeFS without the target branch: records the branch it is asked to create."""
    created = []

    def __init__(self, *a, **k):
        pass

    def branch_exists(self, repo, branch):
        return False

    def default_branch(self, repo):
        return "main"

    def ensure_branch(self, repo, branch, source):
        self.created.append((branch, source))


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
    assert sync_mod.dataset_prefix() == "dataset"


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
    # default run reads main/dataset/
    assert (seen["branch"], seen["prefix"]) == ("main", "dataset")
    assert seen["confirm_deletes"] is True


def test_wrapper_name_is_the_data_ref(monkeypatch, wrapper, tmp_path):
    """The second argument names the dataset (= data-ref), so a new name never
    touches another dataset — it used to be an MLflow tag while the files went to
    main regardless."""
    seen = _capture_sync(monkeypatch, wrapper)
    _run_wrapper(monkeypatch, wrapper, tmp_path, "cats")
    assert (seen["branch"], seen["prefix"]) == ("cats", "dataset")


def test_wrapper_data_version_is_refused(monkeypatch, wrapper, tmp_path):
    seen = _capture_sync(monkeypatch, wrapper)
    with pytest.raises(SystemExit, match="--data-version was removed"):
        _run_wrapper(monkeypatch, wrapper, tmp_path, "cats", "--data-version", "v2")
    assert seen == {}


def test_wrapper_refuses_the_outputs_branch(monkeypatch, wrapper, tmp_path):
    seen = _capture_sync(monkeypatch, wrapper)
    with pytest.raises(SystemExit, match="reserved"):
        _run_wrapper(monkeypatch, wrapper, tmp_path, "outputs")
    assert seen == {}


def test_wrapper_new_name_starts_from_from(monkeypatch, wrapper, tmp_path):
    seen = _capture_sync(monkeypatch, wrapper)
    monkeypatch.setattr(wrapper, "LakeFSClient", _NewBranchClient)
    _NewBranchClient.created = []
    _run_wrapper(monkeypatch, wrapper, tmp_path, "cats", "--from", "v1")
    # the branch is created by the sync, after the plan is confirmed
    assert _NewBranchClient.created == []
    assert seen["created_from"] == "v1"


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
    assert (seen["branch"], seen["prefix"]) == ("cats", "dataset")
    assert seen["confirm_deletes"] is True
    assert seen["remove_legacy"] is False
    assert seen["validated"] is True


def _ok_validation(monkeypatch):
    monkeypatch.setattr(cli, "validate_dataset", lambda d: type("R", (), {"ok": True, "report": lambda s: ""})())


def test_cli_sync_refuses_the_outputs_branch(monkeypatch, tmp_path):
    seen = _capture_sync(monkeypatch, cli)
    _ok_validation(monkeypatch)
    with pytest.raises(SystemExit, match="reserved"):
        cli.main(["sync", str(tmp_path), "--url", "https://lakefs.example", "--repo", "r",
                  "--branch", "outputs"])
    assert seen == {}


def test_cli_sync_data_version_is_refused(monkeypatch, tmp_path):
    _capture_sync(monkeypatch, cli)
    with pytest.raises(SystemExit, match="--data-version was removed"):
        cli.main(["sync", str(tmp_path), "--url", "https://lakefs.example", "--repo", "r",
                  "--data-version", "v2"])


def test_cli_sync_new_branch_forks_the_default_branch(monkeypatch, tmp_path):
    seen = _capture_sync(monkeypatch, cli)
    _ok_validation(monkeypatch)
    monkeypatch.setattr(cli, "LakeFSClient", _NewBranchClient)
    _NewBranchClient.created = []
    cli.main(["sync", str(tmp_path), "--url", "https://lakefs.example", "--repo", "r",
              "--branch", "cats"])
    assert _NewBranchClient.created == []  # deferred to the sync
    assert seen["created_from"] == "main"


def test_cli_dry_run_creates_no_branch(monkeypatch, tmp_path):
    seen = _capture_sync(monkeypatch, cli)
    _ok_validation(monkeypatch)
    monkeypatch.setattr(cli, "LakeFSClient", _NewBranchClient)
    _NewBranchClient.created = []
    cli.main(["sync", str(tmp_path), "--url", "https://lakefs.example", "--repo", "r",
              "--branch", "cats", "--from", "v1", "--dry-run"])
    assert _NewBranchClient.created == []
    assert seen["created_from"] == "v1" and seen["dry_run"] is True


def test_cli_skip_validation_is_recorded(monkeypatch, tmp_path):
    seen = _capture_sync(monkeypatch, cli)
    cli.main(["sync", str(tmp_path), "--url", "https://lakefs.example", "--repo", "r",
              "--skip-validation"])
    assert seen["validated"] is False


def test_cli_list_shows_datasets_in_both_layouts(monkeypatch, capsys):
    class _Refs:
        def __init__(self, *a, **k):
            pass

        def list_refs(self, repo, kind):
            if kind == "branches":
                return [{"id": "main", "commit_id": "a" * 40}, {"id": "outputs", "commit_id": "b" * 40},
                        {"id": "cats", "commit_id": "c" * 40}, {"id": "empty", "commit_id": "d" * 40}]
            return [{"id": "v1", "commit_id": "e" * 40}]

        def has_objects(self, repo, ref, prefix):
            files = {"main": ["dataset/main/data.yaml"], "cats": ["dataset/data.yaml"],
                     "v1": ["dataset/table.csv"], "outputs": ["dataset/data.yaml"], "empty": []}
            return any(f.startswith(prefix) for f in files[ref])

    monkeypatch.setattr(cli, "LakeFSClient", _Refs)
    monkeypatch.setattr(cli, "do_login", lambda *a, **k: Credential(token="t"))
    assert cli.main(["list", "--url", "https://lakefs.example", "--repo", "r"]) == 0
    out = capsys.readouterr().out
    assert "main" in out and "dataset/main/ (old layout)" in out
    assert "cats" in out and "v1" in out and "tag" in out
    assert "outputs" not in out and "empty" not in out


# --- deprecated env shim ---

def test_env_shim_lands_on_the_standard_path(monkeypatch, tmp_path):
    mod = _load(ROOT / "dataset_tools" / "upload_to_lakefs_api.py", "upload_to_lakefs_api")
    seen = _capture_sync(monkeypatch, mod)
    for k, v in {"LAKEFS_URL": "https://lakefs.example", "LAKEFS_REPO": "r",
                 "LAKEFS_BRANCH": "cats", "LOCAL_DIR": str(tmp_path)}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("LAKEFS_COOKIE", raising=False)
    monkeypatch.delenv("UPLOAD_PREFIX", raising=False)
    monkeypatch.delenv("LAKEFS_SYNC_YES", raising=False)
    mod.main()
    assert (seen["branch"], seen["prefix"]) == ("cats", "dataset")
    assert seen["confirm_deletes"] is True, "the shim must not delete silently"


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
    plan = sync_mod.SyncPlan(add=[(tmp_path / "x", "dataset/x")],
                             delete=["dataset/old.png"])
    monkeypatch.setattr(sync_mod, "plan_sync", lambda *a, **k: plan)


def test_guard_refuses_without_a_terminal(monkeypatch, tmp_path):
    _plan_with_deletes(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))  # not a tty
    client = _WriteClient()
    with pytest.raises(SystemExit, match="--yes"):
        sync_mod.sync(tmp_path, client, "r", "main", prefix="dataset", confirm_deletes=True)
    assert client.writes == [], "must not upload or delete anything before confirmation"


def test_guard_no_answer_aborts(monkeypatch, tmp_path):
    _plan_with_deletes(monkeypatch, tmp_path)
    tty = io.StringIO("n\n")
    tty.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", tty)
    client = _WriteClient()
    with pytest.raises(SystemExit, match="Aborted"):
        sync_mod.sync(tmp_path, client, "r", "main", prefix="dataset", confirm_deletes=True)
    assert client.writes == []


def test_guard_yes_answer_proceeds(monkeypatch, tmp_path):
    _plan_with_deletes(monkeypatch, tmp_path)
    tty = io.StringIO("y\n")
    tty.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", tty)
    client = _WriteClient()
    assert sync_mod.sync(tmp_path, client, "r", "main", prefix="dataset/main",
                         confirm_deletes=True, concurrency=1) == "c"
    assert ("del", ("r", "main", "dataset/old.png")) in client.writes


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
    """dataset must not list, and so never plan to delete, dataset2/."""
    seen = []

    class _Remote:
        def list_objects(self, repo, ref, prefix=""):
            seen.append(prefix)
            for path in ("dataset/old.png", "dataset2/keep.png"):
                if path.startswith(prefix):
                    yield {"path": path, "checksum": "x"}

    (tmp_path / "data.yaml").write_text("path: .\n")
    plan = sync_mod.plan_sync(tmp_path, _Remote(), "r", "main", "dataset")
    assert seen == ["dataset/"]
    assert plan.delete == ["dataset/old.png"]


class _LegacyRemote:
    """A branch holding an old-layout dataset at dataset/main/ plus a stale flat file."""

    def list_objects(self, repo, ref, prefix=""):
        for path in ("dataset/main/data.yaml", "dataset/main/images/train/a.jpg",
                     "dataset/old.png", "dataset/data.yaml"):
            if path.startswith(prefix):
                yield {"path": path, "checksum": "x"}


def test_sync_keeps_an_old_layout_dataset(tmp_path):
    """Apps on older step code still read dataset/<branch>/ (one repo serves the
    whole project), so the mirror must not wipe it — with or without data.yaml."""
    (tmp_path / "data.yaml").write_text("path: .\n")
    plan = sync_mod.plan_sync(tmp_path, _LegacyRemote(), "r", "main", "dataset")
    assert plan.legacy == ["dataset/main/"]
    assert plan.delete == ["dataset/old.png"]


def test_a_new_branch_does_not_keep_another_datasets_old_folder(tmp_path):
    """cats copied from main inherits main's dataset/main/: nobody reads it on
    cats, so it must not be kept (qat/quant/HPC would download it every run)."""
    (tmp_path / "data.yaml").write_text("path: .\n")
    plan = sync_mod.plan_sync(tmp_path, _LegacyRemote(), "r", "main", "dataset", name="cats")
    assert plan.legacy == []
    assert "dataset/main/images/train/a.jpg" in plan.delete


class _CreatingClient(_WriteClient):
    """Records branch creation/deletion; uploads fail when told to."""

    def __init__(self, fail=False):
        super().__init__()
        self.fail = fail

    def ensure_branch(self, repo, branch, source):
        self.writes.append(("create", (branch, source)))

    def delete_branch(self, repo, branch):
        self.writes.append(("drop", (branch,)))

    def upload_object(self, *a):
        if self.fail:
            raise sync_mod.LakeFSError("boom")
        super().upload_object(*a)


def test_a_new_branch_is_created_only_after_confirmation(monkeypatch, tmp_path):
    _plan_with_deletes(monkeypatch, tmp_path)
    tty = io.StringIO("n\n")
    tty.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", tty)
    client = _CreatingClient()
    with pytest.raises(SystemExit, match="Aborted"):
        sync_mod.sync(tmp_path, client, "r", "cats", prefix="dataset",
                      confirm_deletes=True, created_from="main")
    assert client.writes == [], "an aborted upload must not leave a copy of main named cats"


def test_a_new_branch_is_created_before_the_upload(monkeypatch, tmp_path):
    _plan_with_deletes(monkeypatch, tmp_path)
    client = _CreatingClient()
    sync_mod.sync(tmp_path, client, "r", "cats", prefix="dataset", concurrency=1,
                  created_from="main")
    assert client.writes[0] == ("create", ("cats", "main"))


def test_a_failed_upload_removes_the_new_branch(monkeypatch, tmp_path):
    _plan_with_deletes(monkeypatch, tmp_path)
    client = _CreatingClient(fail=True)
    with pytest.raises(SystemExit):
        sync_mod.sync(tmp_path, client, "r", "cats", prefix="dataset", concurrency=1,
                      created_from="main")
    assert client.writes[0] == ("create", ("cats", "main"))
    assert client.writes[-1] == ("drop", ("cats",))


def test_sync_remove_legacy_deletes_it(tmp_path):
    (tmp_path / "data.yaml").write_text("path: .\n")
    plan = sync_mod.plan_sync(tmp_path, _LegacyRemote(), "r", "main", "dataset", remove_legacy=True)
    assert plan.legacy == []
    assert sorted(plan.delete) == ["dataset/main/data.yaml", "dataset/main/images/train/a.jpg",
                                   "dataset/old.png"]


def test_delete_prompt_names_the_branch_a_new_one_was_copied_from(monkeypatch, tmp_path, capsys):
    _plan_with_deletes(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))  # not a tty
    with pytest.raises(SystemExit):
        sync_mod.sync(tmp_path, _WriteClient(), "r", "cats", prefix="dataset",
                      confirm_deletes=True, created_from="main")
    assert "copy of 'main'" in capsys.readouterr().out
