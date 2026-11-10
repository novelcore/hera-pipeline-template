"""The example step's results: one merge commit per step per run, a retry is a success."""
from conftest import load_step
from kaos_lib import datasets

CFG = {"experiment": {"name": "exp1"}, "dataset": "dataset-default@latest"}


def _write(client, monkeypatch):
    hello = load_step("hello_world")
    ref = datasets.DatasetRef.parse(CFG["dataset"])
    info = {"dataset": CFG["dataset"], "dataset_commit": datasets.resolve(ref, client)}
    monkeypatch.setenv("CHECKPOINT_BUCKET", "outputs-myapp")
    monkeypatch.setenv("KUBECORE_RUN_ID", "wf-abc")
    data_yaml = hello.read_dataset(ref.with_commit(info["dataset_commit"]), client)
    return lambda: hello.write_result(CFG, info, data_yaml, client)


def test_should_merge_one_commit_and_leave_no_run_branch(client, fake, monkeypatch):
    _write(client, monkeypatch)()
    merges = [e for e in fake.repos["outputs-myapp"]["commit_log"] if e[0] == "main"]
    assert len(merges) == 1
    assert set(fake.repos["outputs-myapp"]["branches"]) == {"main"}, "the run branch is gone after success"


def test_should_succeed_when_the_step_is_retried_with_the_same_content(client, monkeypatch):
    write = _write(client, monkeypatch)
    first = write()
    assert write() == first
