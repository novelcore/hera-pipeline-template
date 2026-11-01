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


def main_commits(fake):
    return [e for e in fake.repos["outputs-myapp"]["commit_log"] if e[0] == "main"]


def test_write_run_one_commit_on_main_under_run_prefix(fake, client, run_dir):
    commit = outputs.write_run("myapp", "exp1", "run-7", run_dir, client=client)
    assert [c for _, c, *_ in main_commits(fake)] == [commit]          # the merge is main's only new commit
    assert fake.head("outputs-myapp") == commit
    tree = fake.tree("outputs-myapp", commit)
    assert set(tree) == {"checkpoints/exp1/run-7/weights/best.pt", "checkpoints/exp1/run-7/results.csv"}
    assert "exp1/run-7" in main_commits(fake)[0][2]
    assert "run-run-7" not in fake.repos["outputs-myapp"]["branches"]    # run branch is deleted


def test_write_run_never_stages_on_main(fake, client, run_dir):
    outputs.write_run("myapp", "exp1", "run-7", run_dir, client=client)
    assert fake.writes and all(branch == "run-run-7" for _, _, branch, _ in fake.writes)


def test_write_run_two_runs_two_commits(fake, client, run_dir):
    first = outputs.write_run("myapp", "exp1", "run-1", run_dir, client=client)
    second = outputs.write_run("myapp", "exp1", "run-2", run_dir, kind="reports", client=client)
    assert first != second and len(main_commits(fake)) == 2
    tree = fake.tree("outputs-myapp", "main")
    assert "checkpoints/exp1/run-1/results.csv" in tree and "reports/exp1/run-2/results.csv" in tree


def test_write_run_interleaved_runs_do_not_mix(fake, client, run_dir, tmp_path, monkeypatch):
    """Run B starts (branches from main) before run A merges; both land intact, one commit each."""
    other = tmp_path / "other"
    other.mkdir()
    (other / "b.pt").write_bytes(b"B")
    real_merge, started = client.merge, {}

    def merge_after_b_started(repo, source, dest, message, metadata=None):
        if not started and source == "run-A":
            started["b"] = outputs.write_run("myapp", "e", "B", other, client=client)  # B fully runs inside A
        return real_merge(repo, source, dest, message, metadata)

    monkeypatch.setattr(client, "merge", merge_after_b_started)
    a = outputs.write_run("myapp", "e", "A", run_dir, client=client)
    assert started["b"] != a and len(main_commits(fake)) == 2
    tree = fake.tree("outputs-myapp", "main")
    assert "checkpoints/e/A/results.csv" in tree and "checkpoints/e/B/b.pt" in tree
    assert all("/A/" not in p for p in tree if "/B/" in p)


def test_write_run_rerun_same_id_replaces_stale_branch(fake, client, run_dir):
    fake.repos["outputs-myapp"]["branches"]["run-r1"] = {"commit": fake.head("outputs-myapp"),
                                                         "base": fake.head("outputs-myapp"), "staged": {"junk": b"x"}}
    commit = outputs.write_run("myapp", "e", "r1", run_dir, client=client)
    assert "junk" not in fake.tree("outputs-myapp", commit)


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
