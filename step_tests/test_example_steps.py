"""The example steps: pin once, read the pinned commit, write one commit to outputs-<app>."""
import json

import pytest
import yaml
from conftest import load_step
from kaos_lib.errors import DatasetError

CFG = {"experiment": {"name": "exp1"}, "dataset": "dataset-default@latest"}


def test_should_record_the_commit_the_choice_resolves_to(client, fake):
    info = load_step("dataset_loading").pin("dataset-default@v1", client)
    assert info == {"dataset": "dataset-default@v1", "dataset_repo": "dataset-default",
                    "dataset_version": "v1", "dataset_commit": fake.head("dataset-default")}


def test_should_resolve_latest_to_the_head_of_main(client, fake):
    info = load_step("dataset_loading").pin("dataset-default@latest", client)
    assert info["dataset_commit"] == fake.head("dataset-default")


@pytest.mark.parametrize("bad", ["main", "dataset-default", "dataset-default@", "", None, "dataset-default@v9"])
def test_should_refuse_a_dataset_that_is_not_a_pickable_version(client, bad):
    with pytest.raises(DatasetError):
        load_step("dataset_loading").pin(bad, client)


def test_should_read_the_pinned_commit_even_when_latest_moves(client, fake):
    hello = load_step("hello_world")
    info = load_step("dataset_loading").pin("dataset-default@latest", client)
    # someone merges a new dataset version while the run is going
    r = fake.repos["dataset-default"]
    moved = dict(r["commits"][info["dataset_commit"]])
    moved["data.yaml"] = b"path: .\ntrain: images/train\nval: images/val\nnc: 1\nnames:\n  0: z\n"
    r["commits"]["c-new"] = moved
    r["branches"]["main"]["commit"] = "c-new"
    data_yaml = hello.read_dataset(info, client)
    assert yaml.safe_load(data_yaml.read_text())["nc"] == 2, "still the commit dataset-loading pinned"


def test_should_stop_when_no_commit_was_pinned(client):
    with pytest.raises(SystemExit):
        load_step("hello_world").read_dataset({"dataset": "dataset-default@latest"}, client)


def test_should_write_one_commit_to_the_apps_outputs_repository(client, fake, monkeypatch):
    hello = load_step("hello_world")
    info = load_step("dataset_loading").pin("dataset-default@v1", client)
    monkeypatch.setenv("CHECKPOINT_BUCKET", "outputs-myapp")
    monkeypatch.setenv("KAOS_RUN_ID", "wf-abc")
    commit = hello.write_result(CFG, info, hello.read_dataset(info, client), client)
    assert fake.head("outputs-myapp") == commit
    tree = fake.tree("outputs-myapp", commit)
    assert set(tree) == {"checkpoints/exp1/wf-abc/hello.json"}
    assert json.loads(tree["checkpoints/exp1/wf-abc/hello.json"])["dataset_commit"] == info["dataset_commit"]


def test_should_still_read_the_deprecated_run_id_name(client, fake, monkeypatch):
    """A platform that only sets KUBECORE_RUN_ID (older engine) still names the run."""
    hello = load_step("hello_world")
    info = load_step("dataset_loading").pin("dataset-default@v1", client)
    monkeypatch.setenv("CHECKPOINT_BUCKET", "outputs-myapp")
    monkeypatch.setenv("KUBECORE_RUN_ID", "wf-old")
    commit = hello.write_result(CFG, info, hello.read_dataset(info, client), client)
    assert set(fake.tree("outputs-myapp", commit)) == {"checkpoints/exp1/wf-old/hello.json"}
