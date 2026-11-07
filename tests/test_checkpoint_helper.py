"""The checkpoint persistence helper (kubecore/checkpoint_helper.py) against an in-process lakeFS.

Covers: save as one archive plus manifest, the two-copy bound, restore of the newest VERIFIED copy,
skipping a corrupt copy, deletion on success and keeping on failure, copies on the stop signal,
expiry, a safe extract, and "never fails the step" when lakeFS is missing or down.
Run:  python -m pytest tests/ -v
"""
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fake_lakefs_http import FakeLakeFS  # noqa: E402
from kubecore import checkpoint_helper as h  # noqa: E402

KEY = "resume/wf-1/train"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "SETTLE_SECONDS", 0)
    fake = FakeLakeFS()
    endpoint = fake.start()
    folder, stage = tmp_path / "ckpt", tmp_path / "stage"
    folder.mkdir()
    stage.mkdir()
    exit_file = tmp_path / "exitcode"
    env = {"KAOS_CHECKPOINT_DIR": str(folder), "LAKEFS_ENDPOINT": endpoint, "LAKEFS_ACCESS_KEY": "ak",
           "LAKEFS_SECRET_KEY": "sk", "CKPT_REPO": "outputs-app", "CKPT_KEY": "wf-1/train",
           "CKPT_STAGE": str(stage), "CKPT_EXIT_FILE": str(exit_file), "CKPT_POLL_SECONDS": "0.01",
           "CKPT_GRACE_SECONDS": "6"}
    cfg = h.Config(env)
    api = h.LakeFS(cfg)
    assert api.ensure_branch()
    yield type("World", (), {"fake": fake, "cfg": cfg, "api": api, "folder": folder, "exit_file": exit_file,
                             "env": env, "branch": fake.branches["kaos-checkpoints"]})
    fake.stop()


def write(world, name, data):
    path = world.folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def objects(world):
    return sorted(world.branch)


def test_should_save_one_archive_and_a_manifest_when_the_folder_has_files(world):
    write(world, "weights/last.pt", b"epoch1")
    took, signature = h.copy_once(world.api, None)
    names = objects(world)
    assert [n.rsplit(".", 1)[1] for n in names] == ["json", "tar"]
    assert all(n.startswith(KEY + "/ckpt-") for n in names)
    assert signature and took >= 0


def test_should_not_save_again_when_nothing_changed(world):
    write(world, "last.pt", b"a")
    _, signature = h.copy_once(world.api, None)
    h.copy_once(world.api, signature)
    assert len(objects(world)) == 2


def test_should_keep_at_most_two_copies(world):
    signature = None
    for i in range(4):
        write(world, "last.pt", b"epoch%d" % i)
        _, signature = h.copy_once(world.api, signature)
        time.sleep(1.05)     # copy names carry a one-second clock
    assert len([n for n in objects(world) if n.endswith(".json")]) == 2
    assert len([n for n in objects(world) if n.endswith(".tar")]) == 2


def test_should_restore_the_newest_copy_into_an_empty_folder(world, tmp_path):
    write(world, "weights/last.pt", b"epoch-7")
    write(world, "kaos-run.json", b"{}")
    h.copy_once(world.api, None)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    world.cfg.folder = str(fresh)
    assert h.restore(world.api) is True
    assert (fresh / "weights" / "last.pt").read_bytes() == b"epoch-7"
    assert oct((fresh / "weights" / "last.pt").stat().st_mode & 0o777) == "0o666"


def test_should_skip_a_copy_whose_checksum_does_not_verify_and_use_the_previous_one(world, tmp_path):
    write(world, "last.pt", b"good-1")
    _, signature = h.copy_once(world.api, None)
    time.sleep(1.05)
    write(world, "last.pt", b"good-2-newer")
    h.copy_once(world.api, signature)
    newest = sorted(n for n in objects(world) if n.endswith(".tar"))[-1]
    data, mtime = world.branch[newest]
    world.branch[newest] = (data[:-10] + b"CORRUPTED!", mtime)     # same size, wrong bytes
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    world.cfg.folder = str(fresh)
    assert h.restore(world.api) is True
    assert (fresh / "last.pt").read_bytes() == b"good-1"


def test_should_restore_nothing_when_there_is_no_copy(world, tmp_path):
    assert h.restore(world.api) is False


def test_should_remove_every_copy_when_the_step_succeeds(world):
    write(world, "last.pt", b"a")
    h.copy_once(world.api, None)
    h.finish(world.api, 0)
    assert objects(world) == []


def test_should_keep_the_copies_when_the_step_fails_by_itself(world):
    write(world, "last.pt", b"a")
    h.copy_once(world.api, None)
    h.finish(world.api, 1)
    assert len(objects(world)) == 2


def test_should_delete_copies_when_the_sidecar_sees_exit_code_zero(world):
    write(world, "last.pt", b"a")
    h.copy_once(world.api, None)
    world.exit_file.write_text("0")
    h.run_watch(world.cfg)
    assert objects(world) == []


def test_should_copy_at_once_when_stopped_before_the_step_ends(world):
    write(world, "last.pt", b"a")
    h.on_stop(world.api, time.time() - world.cfg.grace + 4, None)   # grace nearly spent: no waiting
    assert len(objects(world)) == 2


def test_should_keep_copies_untouched_when_the_stop_comes_after_the_step_ended_with_85(world):
    write(world, "last.pt", b"a")
    h.copy_once(world.api, None)
    world.exit_file.write_text("85")
    # the step already ended with "saved, continue me": the stop is Argo's, keep what exists
    h.on_stop(world.api, time.time(), None)
    assert len(objects(world)) == 2


def test_should_expire_copies_of_runs_older_than_the_retention(world):
    world.branch["resume/old-wf/step/ckpt-1.tar"] = (b"x", time.time() - 9 * 86400)
    world.branch["resume/new-wf/step/ckpt-1.tar"] = (b"x", time.time())
    h.expire(world.api)
    assert list(world.branch) == ["resume/new-wf/step/ckpt-1.tar"]


def test_should_refuse_an_archive_entry_outside_the_folder(world, tmp_path):
    import tarfile
    bad = tmp_path / "bad.tar"
    with tarfile.open(bad, "w") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        import io
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(RuntimeError):
        h.unpack(str(bad), str(world.folder))
    assert not (tmp_path / "escape.txt").exists()


def test_should_start_without_a_checkpoint_when_the_repository_is_missing(world):
    world.fake.repo = "other"
    h.run_restore(world.cfg)     # must not raise
    assert os.listdir(world.folder) == []


def test_should_not_fail_the_step_when_lakefs_is_down(world, capsys):
    world.fake.stop()
    h.run_restore(world.cfg)
    assert "starts without" in capsys.readouterr().err


def test_should_do_nothing_when_the_settings_are_incomplete(monkeypatch, tmp_path):
    for var in ("KAOS_CHECKPOINT_DIR", "LAKEFS_ENDPOINT", "CKPT_REPO"):
        monkeypatch.delenv(var, raising=False)
    assert h.main(["helper", "watch"]) == 0
