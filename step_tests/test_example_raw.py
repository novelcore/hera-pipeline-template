"""The example step reads whatever format the repository is labelled with; no label means plain files."""
import json

from conftest import load_step

CFG = {"experiment": {"name": "exp1"}, "dataset": "dataset-plain@latest"}


def test_should_read_an_unlabelled_dataset_as_a_folder_and_report_its_files(client, fake, monkeypatch):
    fake.add_repo("dataset-plain", files={"a.txt": b"1", "sub/b.txt": b"2"})
    hello = load_step("hello_world")
    info = load_step("dataset_loading").pin("dataset-plain@latest", client)
    entry = hello.read_dataset(info, client)
    assert entry.is_dir() and (entry / "sub" / "b.txt").read_bytes() == b"2"
    assert hello.describe(entry) == {"files": 2}
    monkeypatch.setenv("CHECKPOINT_BUCKET", "outputs-myapp")
    monkeypatch.setenv("KUBECORE_RUN_ID", "wf-raw")
    commit = hello.write_result(CFG, info, entry, client)
    tree = fake.tree("outputs-myapp", commit)
    assert json.loads(tree["checkpoints/exp1/wf-raw/hello.json"])["files"] == 2


def test_should_report_the_classes_of_a_labelled_dataset(client, monkeypatch):
    hello = load_step("hello_world")
    info = load_step("dataset_loading").pin("dataset-default@v1", client)
    assert hello.describe(hello.read_dataset(info, client)) == {"classes": {0: "a", 1: "b"}}
