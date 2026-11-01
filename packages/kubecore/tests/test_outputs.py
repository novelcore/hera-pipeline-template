"""outputs: one commit per run on outputs-<app> main."""
import pytest

from kubecore import outputs
from kubecore.errors import DatasetError


@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "ckpt"
    (d / "weights").mkdir(parents=True)
    (d / "weights" / "best.pt").write_bytes(b"best")
    (d / "results.csv").write_text("epoch\n1\n")
    return d


def test_outputs_repo_name():
    assert outputs.outputs_repo("myapp") == "outputs-myapp"
    assert outputs.outputs_repo("outputs-myapp") == "outputs-myapp"
    with pytest.raises(DatasetError):
        outputs.outputs_repo("Bad_App")


def test_write_run_one_commit_under_run_prefix(fake, client, run_dir):
    commit = outputs.write_run("myapp", "exp1", "run-7", run_dir, client=client)
    r = fake.repos["outputs-myapp"]
    assert [(b, c) for b, c, *_ in r["commit_log"]] == [("main", commit)]
    tree = fake.tree("outputs-myapp", commit)
    assert set(tree) == {"checkpoints/exp1/run-7/weights/best.pt", "checkpoints/exp1/run-7/results.csv"}
    assert "exp1/run-7" in r["commit_log"][0][2]


def test_write_run_two_runs_two_commits(fake, client, run_dir):
    first = outputs.write_run("myapp", "exp1", "run-1", run_dir, client=client)
    second = outputs.write_run("myapp", "exp1", "run-2", run_dir, kind="reports", client=client)
    assert first != second and len(fake.repos["outputs-myapp"]["commit_log"]) == 2
    tree = fake.tree("outputs-myapp", "main")
    assert "checkpoints/exp1/run-1/results.csv" in tree and "reports/exp1/run-2/results.csv" in tree


def test_write_run_never_touches_dataset_repos(fake, client, run_dir):
    outputs.write_run("myapp", "e", "r", run_dir, client=client)
    assert {repo for _, repo, _, _ in fake.writes} == {"outputs-myapp"}


@pytest.mark.parametrize("kwargs", [{"experiment": "a/b"}, {"run": ".."}, {"kind": ""}, {"run": ""}])
def test_write_run_rejects_bad_path_parts(fake, client, run_dir, kwargs):
    args = {"experiment": "e", "run": "r", "kind": "checkpoints", **kwargs}
    with pytest.raises(DatasetError, match="invalid"):
        outputs.write_run("myapp", args["experiment"], args["run"], run_dir, kind=args["kind"], client=client)


def test_write_run_missing_repo_and_empty_dir(fake, client, run_dir, tmp_path):
    with pytest.raises(DatasetError, match="outputs-ghost does not exist"):
        outputs.write_run("ghost", "e", "r", run_dir, client=client)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(DatasetError, match="no files"):
        outputs.write_run("myapp", "e", "r", empty, client=client)
