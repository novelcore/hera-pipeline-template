"""The generic check: a folder with files passes; nothing format-specific."""
from __future__ import annotations

from dataset_cli.validate import validate_dataset


def test_any_files_pass(tmp_path):
    (tmp_path / "a.csv").write_text("x,y\n1,2\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.bin").write_bytes(b"\x00\x01")
    r = validate_dataset(tmp_path)
    assert r.ok and r.stats["files"] == 2


def test_empty_folder_fails(tmp_path):
    r = validate_dataset(tmp_path)
    assert not r.ok and "no files" in r.errors[0]


def test_missing_folder_fails(tmp_path):
    r = validate_dataset(tmp_path / "nope")
    assert not r.ok and "not a folder" in r.errors[0]


def test_system_junk_warns_but_does_not_block(tmp_path):
    (tmp_path / "data.txt").write_text("ok")
    (tmp_path / ".DS_Store").write_bytes(b"")
    r = validate_dataset(tmp_path)
    assert r.ok and r.warnings and ".DS_Store" in r.warnings[0]


def test_only_junk_counts_as_empty(tmp_path):
    (tmp_path / ".DS_Store").write_bytes(b"")
    assert not validate_dataset(tmp_path).ok
