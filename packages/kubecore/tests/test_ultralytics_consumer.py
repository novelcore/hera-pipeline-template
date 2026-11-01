"""ultralytics consumer: materialize, (repo, commit) cache, staged copy."""
import json

import pytest
import yaml

from conftest import write_dataset
from kubecore import datasets
from kubecore.errors import DatasetError

REF = datasets.DatasetRef.parse("dataset-default@v1")


@pytest.fixture
def populated(fake, dataset_dir):
    r = fake.repos["dataset-default"]
    files = {p.relative_to(dataset_dir).as_posix(): p.read_bytes()
             for p in dataset_dir.rglob("*") if p.is_file()}
    files["notes/ignored.txt"] = b"not training data"
    files["checkpoints/m.pt"] = b"nor this"
    r["commits"]["c-data"] = files
    r["branches"]["main"]["commit"] = "c-data"
    fake.tag("dataset-default", "v1")
    return fake


def downloads(fake):
    return [c for c in fake.calls if c[0] == "GET" and c[1].endswith("/objects")]


def test_materialize_downloads_only_training_files_and_rewrites_path(populated, client, tmp_path):
    dest = tmp_path / "out"
    data_yaml = datasets.materialize(REF, dest, client=client)
    assert data_yaml == dest / "data.yaml"
    assert yaml.safe_load(data_yaml.read_text())["path"] == str(dest.resolve())
    assert (dest / "images/train/a.jpg").read_bytes() == b"img-a"
    assert (dest / "labels/val/b.txt").is_file()
    assert not (dest / "notes").exists() and not (dest / "checkpoints").exists()


def test_materialize_second_call_downloads_nothing(populated, client, tmp_path):
    dest = tmp_path / "out"
    datasets.materialize(REF, dest, client=client)
    n = len(downloads(populated))
    assert n > 0
    assert datasets.materialize(REF, dest, client=client) == dest / "data.yaml"
    assert len(downloads(populated)) == n


def test_materialize_default_location_is_keyed_by_repo_and_commit(populated, client, tmp_path):
    data_yaml = datasets.materialize(REF, client=client)
    assert data_yaml.parent == tmp_path / "cache" / "dataset-default" / "c-data"


def test_materialize_new_commit_replaces_old_copy(populated, client, tmp_path):
    dest = tmp_path / "out"
    datasets.materialize(REF, dest, client=client)
    r = populated.repos["dataset-default"]
    r["commits"]["c-two"] = {"data.yaml": b"nc: 1\nnames: [a]\ntrain: images/train\nval: images/val\n",
                             "images/train/z.jpg": b"z"}
    r["branches"]["main"]["commit"] = "c-two"
    datasets.materialize(datasets.DatasetRef.parse("dataset-default@latest"), dest, client=client)
    assert (dest / "images/train/z.jpg").is_file() and not (dest / "images/train/a.jpg").exists()
    assert json.loads((dest / ".kubecore-dataset.json").read_text())["commit"] == "c-two"


def test_materialize_refuses_foreign_nonempty_dest(populated, client, tmp_path):
    dest = tmp_path / "mine"
    dest.mkdir()
    (dest / "precious.txt").write_text("keep")
    with pytest.raises(DatasetError, match="not empty"):
        datasets.materialize(REF, dest, client=client)
    assert (dest / "precious.txt").read_text() == "keep"


def test_materialize_uses_staged_copy_without_downloading(populated, client, tmp_path, monkeypatch):
    staged = write_dataset(tmp_path / "lustre" / "dataset-default" / "c-data")
    (staged / ".kaos-ready").write_text("")
    monkeypatch.setenv("KUBECORE_STAGED_DIR", str(staged))
    data_yaml = datasets.materialize(REF, tmp_path / "out", client=client)
    assert yaml.safe_load(data_yaml.read_text())["path"] == str(staged)    # train reads the resident copy
    assert downloads(populated) == []
    assert not (tmp_path / "out" / "images").exists()


def test_staged_dir_for_another_commit_is_ignored(populated, client, tmp_path, monkeypatch):
    staged = write_dataset(tmp_path / "lustre" / "other-commit")
    monkeypatch.setenv("KUBECORE_STAGED_DIR", str(staged))
    datasets.materialize(REF, tmp_path / "out", client=client)
    assert len(downloads(populated)) > 0


def test_materialize_unknown_version_is_clear(populated, client):
    with pytest.raises(DatasetError, match="no version v9"):
        datasets.materialize(datasets.DatasetRef.parse("dataset-default@v9"), client=client)
