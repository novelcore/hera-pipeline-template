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
    monkeypatch.setenv("KAOS_RUN_ID", "wf-raw")
    commit = hello.write_result(CFG, info, entry, client)
    tree = fake.tree("outputs-myapp", commit)
    assert json.loads(tree["checkpoints/exp1/wf-raw/hello.json"])["files"] == 2


def test_should_report_the_classes_of_a_labelled_dataset(client, monkeypatch):
    hello = load_step("hello_world")
    info = load_step("dataset_loading").pin("dataset-default@v1", client)
    assert hello.describe(hello.read_dataset(info, client)) == {"classes": {0: "a", 1: "b"}}


def test_should_report_a_dataset_with_no_files_instead_of_failing(client, fake, monkeypatch, capsys):
    # A new project's dataset-default holds only its initial commit: the first run must still succeed.
    fake.add_repo("dataset-empty", files={})
    hello = load_step("hello_world")
    info = load_step("dataset_loading").pin("dataset-empty@latest", client)
    read, write = hello.read_dataset, hello.write_result
    monkeypatch.setattr(hello, "read_dataset", lambda i: read(i, client))        # main() uses the default client
    monkeypatch.setattr(hello, "write_result", lambda c, i, e: write(c, i, e, client))
    monkeypatch.setenv("CHECKPOINT_BUCKET", "outputs-myapp")
    monkeypatch.setenv("KAOS_RUN_ID", "wf-empty")
    monkeypatch.setattr("sys.argv", ["entry", "--params", json.dumps(CFG), "--dataset-info", json.dumps(info)])
    hello.main()
    assert "holds no files yet" in capsys.readouterr().out
    tree = fake.tree("outputs-myapp", fake.head("outputs-myapp"))
    assert json.loads(tree["checkpoints/exp1/wf-empty/hello.json"])["files"] == 0


def test_should_still_run_on_a_kaos_lib_without_empty_dataset(client, fake, monkeypatch):
    # An app pinned to kaos-lib before 0.4.0rc3 builds this step against a kaos-lib with no
    # EmptyDataset: the step must import and read a dataset that has files.
    import kaos_lib.errors
    monkeypatch.delattr(kaos_lib.errors, "EmptyDataset")
    hello = load_step("hello_world")
    info = load_step("dataset_loading").pin("dataset-default@v1", client)
    assert hello.describe(hello.read_dataset(info, client)) == {"classes": {0: "a", 1: "b"}}
