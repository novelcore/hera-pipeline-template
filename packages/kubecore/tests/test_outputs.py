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


def branches(fake):
    return set(fake.repos["outputs-myapp"]["branches"])


def test_run_branch_name_is_sanitised_per_kind():
    assert outputs.run_branch("run 7/x", "reports") == "run-run-7-x-reports"


def test_write_run_one_commit_on_main_under_run_prefix(fake, client, run_dir):
    commit = outputs.write_run("myapp", "exp1", "run-7", run_dir, client=client)
    assert [c for _, c, *_ in main_commits(fake)] == [commit]          # the merge is main's only new commit
    assert fake.head("outputs-myapp") == commit
    tree = fake.tree("outputs-myapp", commit)
    assert set(tree) == {"checkpoints/exp1/run-7/weights/best.pt", "checkpoints/exp1/run-7/results.csv"}
    assert "exp1/run-7" in main_commits(fake)[0][2]
    assert branches(fake) == {"main"}                                   # no branch left after success


def test_write_run_never_stages_on_main(fake, client, run_dir):
    outputs.write_run("myapp", "exp1", "run-7", run_dir, client=client)
    assert fake.writes and all(branch == "run-run-7-checkpoints" for _, _, branch, _ in fake.writes)


def test_write_run_two_runs_two_commits(fake, client, run_dir):
    first = outputs.write_run("myapp", "exp1", "run-1", run_dir, client=client)
    second = outputs.write_run("myapp", "exp1", "run-2", run_dir, kind="reports", client=client)
    assert first != second and len(main_commits(fake)) == 2
    tree = fake.tree("outputs-myapp", "main")
    assert "checkpoints/exp1/run-1/results.csv" in tree and "reports/exp1/run-2/results.csv" in tree


def test_interleaved_runs_do_not_mix(fake, client, run_dir, tmp_path, monkeypatch):
    """Run B fully runs while A is about to merge; both land intact, one main commit each."""
    other = tmp_path / "other"
    other.mkdir()
    (other / "b.pt").write_bytes(b"B")
    real_merge, started = client.merge, {}

    def merge_after_b_started(repo, source, dest, message, metadata=None, **kw):
        if not started and source == "run-A-checkpoints":
            started["b"] = outputs.write_run("myapp", "e", "B", other, client=client)
        return real_merge(repo, source, dest, message, metadata, **kw)

    monkeypatch.setattr(client, "merge", merge_after_b_started)
    a = outputs.write_run("myapp", "e", "A", run_dir, client=client)
    assert started["b"] != a and len(main_commits(fake)) == 2
    tree = fake.tree("outputs-myapp", "main")
    assert "checkpoints/e/A/results.csv" in tree and "checkpoints/e/B/b.pt" in tree


def test_two_kinds_of_one_run_in_parallel(fake, client, run_dir, tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "m.json").write_text("{}")
    with outputs.run("myapp", "e", "r1", "checkpoints", client=client) as ck, \
            outputs.run("myapp", "e", "r1", "reports", client=client) as rp:
        assert ck.branch != rp.branch
        ck.save(run_dir)
        rp.save(reports)
    assert len(main_commits(fake)) == 2 and branches(fake) == {"main"}
    tree = fake.tree("outputs-myapp", "main")
    assert "checkpoints/e/r1/results.csv" in tree and "reports/e/r1/m.json" in tree


def test_resume_after_simulated_crash(fake, client, run_dir, tmp_path):
    """A crash inside the block keeps the branch and its saved epochs; the retry resumes and finishes."""
    epoch1 = tmp_path / "e1"
    epoch1.mkdir()
    (epoch1 / "epoch1.pt").write_bytes(b"e1")
    with pytest.raises(RuntimeError):
        with outputs.run("myapp", "e", "r1", client=client) as r:
            r.save(epoch1, message="epoch 1")
            raise RuntimeError("pod preempted")
    assert "run-r1-checkpoints" in branches(fake) and main_commits(fake) == []   # no merge, no delete
    assert "checkpoints/e/r1/epoch1.pt" not in fake.tree("outputs-myapp", "main")

    with outputs.run("myapp", "e", "r1", client=client) as r:                    # the retry reuses the branch
        resumed = r.latest("epoch1.pt", dest=tmp_path / "resume")
        assert resumed.read_bytes() == b"e1"
        r.save(run_dir)
    tree = fake.tree("outputs-myapp", "main")
    assert {"checkpoints/e/r1/epoch1.pt", "checkpoints/e/r1/results.csv"} <= set(tree)
    assert len(main_commits(fake)) == 1 and branches(fake) == {"main"}


def test_every_save_is_durable_on_the_run_branch_before_finish(fake, client, tmp_path):
    f = tmp_path / "ep.pt"
    f.write_bytes(b"1")
    with outputs.run("myapp", "e", "r1", client=client) as r:
        r.save([f])
        assert "checkpoints/e/r1/ep.pt" in fake.tree("outputs-myapp", "run-r1-checkpoints")
        assert main_commits(fake) == []


def test_latest_newest_file_dir_and_nothing(fake, client, tmp_path):
    for n in (1, 2):
        d = tmp_path / f"s{n}"
        d.mkdir()
        (d / f"epoch{n}.pt").write_bytes(b"x" * n)
        with_writer = outputs.RunWriter("myapp", "e", "r1", client=client).open()
        with_writer.save(d)
    r = outputs.RunWriter("myapp", "e", "r1", client=client)
    assert r.latest("nope") is None
    assert r.latest("epoch", dest=tmp_path / "o").name == "epoch2.pt"      # most recently written
    folder = r.latest("", dest=tmp_path / "all")
    assert {p.name for p in folder.iterdir()} == {"epoch1.pt", "epoch2.pt"}


def test_identical_retry_is_a_success_returning_existing_commits(fake, client, run_dir):
    with outputs.run("myapp", "e", "r1", client=client) as r:
        first = r.save(run_dir)
        assert r.save(run_dir) == first                                     # nothing new to commit
    again = outputs.write_run("myapp", "e", "r1", run_dir, client=client)   # whole step re-run after success
    assert again == fake.head("outputs-myapp") and len(main_commits(fake)) == 1


def test_finish_without_saves_returns_main_head(fake, client):
    head = fake.head("outputs-myapp")
    with outputs.run("myapp", "e", "r1", client=client) as r:
        pass
    assert r.finish() == head and branches(fake) == {"main"}


def test_merge_commit_carries_metadata(fake, client, run_dir):
    with outputs.run("myapp", "exp1", "r1", "checkpoints", client=client) as r:
        r.save(run_dir)
        commit = r.finish({"dataset_ref": "dataset-default@v2", "commit": "abc123", "mlflow_run_id": "m1"})
    entry = main_commits(fake)[0]
    assert entry[1] == commit and entry[3] == {
        "app": "myapp", "experiment": "exp1", "run": "r1", "kind": "checkpoints",
        "dataset_ref": "dataset-default@v2", "commit": "abc123", "mlflow_run_id": "m1"}


def test_write_run_accepts_metadata(fake, client, run_dir):
    outputs.write_run("myapp", "e", "r", run_dir, metadata={"mlflow_run_id": "m9"}, client=client)
    assert main_commits(fake)[0][3]["mlflow_run_id"] == "m9"


def test_exception_does_not_merge_even_after_finish_was_not_called(fake, client, run_dir):
    with pytest.raises(ValueError):
        with outputs.run("myapp", "e", "r1", client=client) as r:
            r.save(run_dir)
            raise ValueError("boom")
    assert main_commits(fake) == [] and "run-r1-checkpoints" in branches(fake)


def test_write_run_never_touches_dataset_repos(fake, client, run_dir):
    outputs.write_run("myapp", "e", "r", run_dir, client=client)
    assert {repo for _, repo, _, _ in fake.writes} == {"outputs-myapp"}


@pytest.mark.parametrize("kwargs", [{"experiment": "a/b"}, {"run": ".."}, {"kind": ""}, {"run": ""}])
def test_write_run_rejects_bad_path_parts(fake, client, run_dir, kwargs):
    args = {"experiment": "e", "run": "r", "kind": "checkpoints", **kwargs}
    with pytest.raises(DatasetError, match="invalid"):
        outputs.write_run("myapp", args["experiment"], args["run"], run_dir, kind=args["kind"], client=client)


def test_run_save_rejects_missing_files(fake, client, tmp_path):
    with pytest.raises(DatasetError, match="is not a file"):
        with outputs.run("myapp", "e", "r", client=client) as r:
            r.save([tmp_path / "ghost.pt"])


def test_write_run_missing_repo_and_empty_dir(fake, client, run_dir, tmp_path):
    with pytest.raises(DatasetError, match="outputs-ghost does not exist"):
        outputs.write_run("ghost", "e", "r", run_dir, client=client)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(DatasetError, match="no files"):
        outputs.write_run("myapp", "e", "r", empty, client=client)
