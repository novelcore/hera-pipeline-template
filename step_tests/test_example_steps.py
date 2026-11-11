"""The example step: read the run's dataset at the commit its data lock gives, write one commit to outputs-<app>."""
import json

import yaml
from conftest import load_step
from kaos_lib import datasets

NEW = "a" * 40
CFG = {"experiment": {"name": "exp1"}, "dataset": "dataset-default@latest"}
PARAMS = json.dumps(CFG)


def _move_latest(fake, repo="dataset-default"):
    """Someone merges a new dataset version: `latest` now points at a commit with 1 class."""
    r = fake.repos[repo]
    old = r["branches"]["main"]["commit"]
    moved = dict(r["commits"][old])
    moved["data.yaml"] = b"path: .\ntrain: images/train\nval: images/val\nnc: 1\nnames:\n  0: z\n"
    r["commits"][NEW] = moved
    r["branches"]["main"]["commit"] = NEW
    return old


def _run(hello, client, monkeypatch, run="wf-abc"):
    monkeypatch.setenv("CHECKPOINT_BUCKET", "outputs-myapp")
    monkeypatch.setenv("KUBECORE_RUN_ID", run)
    monkeypatch.setattr("sys.argv", ["entry", "--params", PARAMS])
    hello.main(client)


def test_should_read_the_locked_commit_even_when_latest_moves(client, fake, monkeypatch):
    hello = load_step("hello_world")
    locked = fake.head("dataset-default")
    lock = {"version": 1, "reads": [{"repo": "dataset-default", "ref": "latest", "commit": locked}]}
    monkeypatch.setenv("KAOS_LIB_LOCK", json.dumps(lock))
    assert _move_latest(fake) == locked
    entry = hello.read_dataset(datasets.DatasetRef.parse(CFG["dataset"]), client)
    assert yaml.safe_load(entry.read_text())["nc"] == 2, "still the commit the platform locked"
    _run(hello, client, monkeypatch)
    result = json.loads(fake.tree("outputs-myapp", fake.head("outputs-myapp"))["checkpoints/exp1/wf-abc/hello.json"])
    assert result["dataset"] == "dataset-default@latest"
    assert result["dataset_commit"] == locked, "the result records the commit the lock gave"
    assert result["classes"] == {"0": "a", "1": "b"}


def test_should_read_the_head_when_the_run_has_no_lock(client, fake, monkeypatch):
    hello = load_step("hello_world")
    _move_latest(fake)
    _run(hello, client, monkeypatch)
    result = json.loads(fake.tree("outputs-myapp", fake.head("outputs-myapp"))["checkpoints/exp1/wf-abc/hello.json"])
    assert result["dataset_commit"] == NEW
    assert result["classes"] == {"0": "z"}


def test_should_write_one_commit_to_the_apps_outputs_repository(client, fake, monkeypatch):
    _run(load_step("hello_world"), client, monkeypatch)
    tree = fake.tree("outputs-myapp", fake.head("outputs-myapp"))
    assert set(tree) == {"checkpoints/exp1/wf-abc/hello.json"}
    assert json.loads(tree["checkpoints/exp1/wf-abc/hello.json"])["dataset_commit"] == fake.head("dataset-default")
