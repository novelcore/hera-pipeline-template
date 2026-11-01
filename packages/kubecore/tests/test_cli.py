"""CLI happy paths (next step + link printed) and user-error messages (no tracebacks)."""
import pytest

from kubecore import cli, datasets
from conftest import write_dataset


@pytest.fixture(autouse=True)
def use_fake(fake, monkeypatch):
    monkeypatch.setattr(cli, "_connect", lambda args: fake.client())


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_create_prints_lakefs_url_and_push_hint(capsys, fake):
    code, out, _ = run(capsys, "dataset", "create", "cats", "--classes", "cat,dog", "--description", "pets")
    assert code == 0
    assert "http://lakefs.test/repositories/dataset-cats/objects" in out
    assert "kubecore dataset push" in out and "kubecore dataset pull dataset-cats@latest" in out
    assert "data.yaml" in fake.tree("dataset-cats", "main")


def test_list_shows_datasets_and_next_step(capsys):
    code, out, _ = run(capsys, "dataset", "list")
    assert code == 0 and "dataset-default" in out and "[default]" in out
    assert "kubecore dataset versions dataset-default" in out


def test_versions_empty_then_with_release(capsys):
    _, out, _ = run(capsys, "dataset", "versions", "default")
    assert "no versions yet" in out and "kubecore dataset release dataset-default" in out
    run(capsys, "dataset", "release", "default")
    _, out, _ = run(capsys, "dataset", "versions", "dataset-default")
    assert "v1" in out and "dataset = dataset-default@v1" in out


def test_release_prints_version_and_pipeline_hint(capsys):
    code, out, _ = run(capsys, "dataset", "release", "dataset-default")
    assert code == 0 and "Released dataset-default v1" in out
    assert "dataset = dataset-default@v1" in out


def test_push_prints_pull_request_url(capsys, dataset_dir):
    code, out, _ = run(capsys, "dataset", "push", str(dataset_dir), "dataset-default", "-m", "more images")
    assert code == 0
    assert "http://lakefs.test/repositories/dataset-default/pulls/1" in out
    assert "kubecore dataset release dataset-default" in out


def test_push_invalid_dataset_exit_2_lists_problems(capsys, tmp_path):
    root = write_dataset(tmp_path / "bad", bad_label="7 0.5 0.5 0.1 0.1")
    code, _, err = run(capsys, "dataset", "push", str(root), "dataset-default", "-m", "x")
    assert code == 2 and "nothing was uploaded" in err and "class id 7" in err
    assert "Traceback" not in err


def test_pull_prints_data_yaml_path(capsys, fake, dataset_dir, tmp_path):
    r = fake.repos["dataset-default"]
    r["commits"]["c1"] = {p.relative_to(dataset_dir).as_posix(): p.read_bytes()
                          for p in dataset_dir.rglob("*") if p.is_file()}
    r["branches"]["main"]["commit"] = "c1"
    fake.tag("dataset-default", "v1")
    dest = tmp_path / "local"
    code, out, _ = run(capsys, "dataset", "pull", "dataset-default@v1", str(dest))
    assert code == 0 and f"Ready: {dest}/data.yaml" in out and (dest / "data.yaml").is_file()


def test_validate_ok_and_failing(capsys, dataset_dir, tmp_path):
    code, out, _ = run(capsys, "dataset", "validate", str(dataset_dir))
    assert code == 0 and "valid" in out
    code, _, err = run(capsys, "dataset", "validate", str(tmp_path / "missing"))
    assert code == 2 and "not a directory" in err


@pytest.mark.parametrize("argv,fragment", [
    (["dataset", "pull", "dataset-default"], "not a dataset reference"),
    (["dataset", "pull", "dataset-default@v9"], "no version v9"),
    (["dataset", "create", "x", "--classes", "a"], "invalid dataset name"),
    (["dataset", "create", "cats"], "at least one class name"),
    (["dataset", "pull", "my_repo@main"], "not a valid lakeFS repository name"),
    (["dataset", "create", "default", "--classes", "a"], "already exists"),
    (["dataset", "release", "dataset-ghost"], "does not exist"),
    (["dataset", "versions", "BAD"], "invalid dataset name"),
])
def test_user_errors_are_one_line_without_traceback(capsys, argv, fragment):
    code, _, err = run(capsys, *argv)
    assert code == 1 and err.startswith("ERROR:") and fragment in err
    assert "Traceback" not in err and err.count("\n") == 1


def test_missing_url_error(capsys, monkeypatch):
    monkeypatch.undo()  # use the real _connect
    code, _, err = run(capsys, "dataset", "list")
    assert code == 1 and "cannot determine the lakeFS URL" in err


def test_not_signed_in_error(capsys, monkeypatch):
    monkeypatch.undo()
    monkeypatch.setenv("LAKEFS_ENDPOINT", "http://lakefs.test")
    code, _, err = run(capsys, "dataset", "list")
    assert code == 1 and "kubecore login" in err


def test_push_no_validate_warns_and_uploads(capsys, tmp_path):
    root = write_dataset(tmp_path / "bad", bad_label="7 0.5 0.5 0.1 0.1")
    code, out, err = run(capsys, "dataset", "push", str(root), "dataset-default", "-m", "x", "--no-validate")
    assert code == 0 and "WARNING" in err and "not validated" in err
    assert "/pulls/1" in out
