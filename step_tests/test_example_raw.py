"""The example step reads whatever format the repository is labelled with; no label means plain files."""
import json

from conftest import load_step
from kaos_lib import datasets

CFG = {"experiment": {"name": "exp1"}, "dataset": "dataset-plain@latest"}


def _info(ref_text, client):
    ref = datasets.DatasetRef.parse(ref_text)
    return ref.with_commit(datasets.resolve(ref, client)), {"dataset": ref_text, "dataset_commit": datasets.resolve(ref, client)}


def test_should_read_an_unlabelled_dataset_as_a_folder_and_report_its_files(client, fake, monkeypatch):
    fake.add_repo("dataset-plain", files={"a.txt": b"1", "sub/b.txt": b"2"})
    hello = load_step("hello_world")
    ref, info = _info("dataset-plain@latest", client)
    entry = hello.read_dataset(ref, client)
    assert entry.is_dir() and (entry / "sub" / "b.txt").read_bytes() == b"2"
    assert hello.describe(entry) == {"files": 2}
    monkeypatch.setenv("CHECKPOINT_BUCKET", "outputs-myapp")
    monkeypatch.setenv("KUBECORE_RUN_ID", "wf-raw")
    commit = hello.write_result(CFG, info, entry, client)
    tree = fake.tree("outputs-myapp", commit)
    assert json.loads(tree["checkpoints/exp1/wf-raw/hello.json"])["files"] == 2


def test_should_report_the_classes_of_a_labelled_dataset(client, monkeypatch):
    hello = load_step("hello_world")
    ref, _ = _info("dataset-default@v1", client)
    assert hello.describe(hello.read_dataset(ref, client)) == {"classes": {0: "a", 1: "b"}}


def test_should_report_a_dataset_with_no_files_instead_of_failing(client, fake, monkeypatch, capsys):
    # A new project's dataset-default holds only its initial commit: the first run must still succeed.
    fake.add_repo("dataset-empty", files={})
    hello = load_step("hello_world")
    cfg = {**CFG, "dataset": "dataset-empty@latest"}
    monkeypatch.setenv("CHECKPOINT_BUCKET", "outputs-myapp")
    monkeypatch.setenv("KUBECORE_RUN_ID", "wf-empty")
    monkeypatch.setattr("sys.argv", ["entry", "--params", json.dumps(cfg)])
    hello.main(client)
    assert "holds no files yet" in capsys.readouterr().out
    tree = fake.tree("outputs-myapp", fake.head("outputs-myapp"))
    assert json.loads(tree["checkpoints/exp1/wf-empty/hello.json"])["files"] == 0


def test_should_still_run_on_a_kaos_lib_without_empty_dataset(client, fake, monkeypatch):
    # An app pinned to kaos-lib before 0.4.0rc3 builds this step against a kaos-lib with no
    # EmptyDataset: the step must import and read a dataset that has files.
    import kaos_lib.errors
    monkeypatch.delattr(kaos_lib.errors, "EmptyDataset")
    hello = load_step("hello_world")
    ref, _ = _info("dataset-default@v1", client)
    assert hello.describe(hello.read_dataset(ref, client)) == {"classes": {0: "a", 1: "b"}}
