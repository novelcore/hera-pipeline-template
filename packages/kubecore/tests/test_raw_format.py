"""raw format: any repository, whole tree or a prefix; label-driven format choice; empty datasets."""
import pytest

from conftest import write_dataset
from kubecore import cli, datasets
from kubecore.errors import DatasetError
from kubecore.formats import get_format

FILES = {"a.txt": b"A", "sub/b.txt": b"B", "sub/deep/c.bin": b"C", "other/d.txt": b"D"}


@pytest.fixture
def repo(fake):
    fake.add_repo("my-repo", ns="gs://b/x/my-repo", files=FILES)           # no kaos.template label
    return datasets.DatasetRef.parse("my-repo@latest")


def gets(fake):
    return [c for c in fake.calls if c[0] == "GET" and c[1].endswith("/objects")]


def test_raw_downloads_whole_tree_and_returns_the_directory(repo, fake, client, tmp_path):
    out = datasets.materialize(repo, tmp_path / "all", client=client)
    assert out == tmp_path / "all" and out.is_dir()
    assert {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file() and p.name[0] != "."} == set(FILES)
    assert (out / "sub/deep/c.bin").read_bytes() == b"C"


def test_raw_prefix_downloads_only_that_folder_relative_to_it(repo, fake, client, tmp_path):
    out = datasets.materialize(repo, tmp_path / "sub", client=client, prefix="sub")
    assert {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file() and p.name[0] != "."} == {
        "b.txt", "deep/c.bin"}


def test_raw_cache_is_keyed_by_repo_commit_and_prefix(repo, fake, client, tmp_path):
    whole = datasets.materialize(repo, client=client)
    sub = datasets.materialize(repo, client=client, prefix="sub")
    other = datasets.materialize(repo, client=client, prefix="other/")
    assert len({whole, sub, other}) == 3 and whole.parent == tmp_path / "cache" / "my-repo"
    n = len(gets(fake))
    assert datasets.materialize(repo, client=client) == whole
    assert datasets.materialize(repo, client=client, prefix="sub") == sub     # second calls are free
    assert len(gets(fake)) == n


def test_raw_new_commit_means_new_cache_entry(repo, fake, client):
    first = datasets.materialize(repo, client=client)
    fake.repos["my-repo"]["commits"]["cnew000"] = {"a.txt": b"A2"}
    fake.repos["my-repo"]["branches"]["main"]["commit"] = "cnew000"
    second = datasets.materialize(repo, client=client)
    assert first != second and (second / "a.txt").read_bytes() == b"A2"


def test_raw_pinned_commit(repo, fake, client, tmp_path):
    head = fake.head("my-repo")
    fake.repos["my-repo"]["commits"]["cnew000"] = {"a.txt": b"A2"}
    fake.repos["my-repo"]["branches"]["main"]["commit"] = "cnew000"
    out = datasets.materialize(repo, tmp_path / "o", client=client, commit=head)
    assert (out / "a.txt").read_bytes() == b"A"


def test_raw_uses_staged_dir_whole_and_prefix(repo, fake, client, tmp_path, monkeypatch):
    staged = tmp_path / "lustre" / fake.head("my-repo")
    (staged / "sub").mkdir(parents=True)
    (staged / "sub" / "b.txt").write_text("B")
    (staged / ".kaos-ready").write_text("")
    monkeypatch.setenv("KUBECORE_STAGED_DIR", str(staged))
    assert datasets.materialize(repo, client=client) == staged
    assert datasets.materialize(repo, client=client, prefix="sub") == staged / "sub/"
    assert gets(fake) == []                                               # nothing downloaded
    with pytest.raises(DatasetError, match="no files under missing/"):      # not staged: falls back to a download
        datasets.materialize(repo, client=client, prefix="missing")


def test_raw_empty_prefix_is_a_clear_error(repo, client):
    with pytest.raises(DatasetError, match="holds no files under nothing/"):
        datasets.materialize(repo, client=client, prefix="nothing")


def test_raw_refuses_foreign_nonempty_dest(repo, client, tmp_path):
    (tmp_path / "mine").mkdir()
    (tmp_path / "mine" / "x").write_text("keep")
    with pytest.raises(DatasetError, match="not empty"):
        datasets.materialize(repo, tmp_path / "mine", client=client)


def test_raw_creator_has_no_skeleton_validates_nothing_publishes_as_is(fake, client, tmp_path):
    raw = get_format("raw").creator
    assert raw.skeleton() == {}
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "anything.bin").write_bytes(b"\x00")
    assert raw.validate(junk).ok
    result = raw.publish(junk, "my-repo", "first", client=client)
    assert result.created and fake.repos["my-repo"]["metadata"] == {"kaos.kind": "dataset"}
    assert "anything.bin" in fake.tree("my-repo", result.branch)


# ---- label-driven format choice
def labelled(fake, name, template, files):
    fake.add_repo(name, ns=f"gs://b/x/{name}", metadata={"kaos.template": template} if template else {}, files=files)
    return datasets.DatasetRef.parse(f"{name}@latest")


def ultralytics_files(tmp_path):
    root = write_dataset(tmp_path / "u")
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("label", ["ultralytics", "yolo"])
def test_label_ultralytics_or_alias_selects_the_ultralytics_consumer(fake, client, tmp_path, label):
    ref = labelled(fake, "pics", label, ultralytics_files(tmp_path))
    out = datasets.materialize(ref, client=client)
    assert out.name == "data.yaml"


def test_no_label_or_unknown_label_selects_raw(fake, client, tmp_path):
    for name, label in (("plain", None), ("odd", "something-else")):
        out = datasets.materialize(labelled(fake, name, label, FILES), client=client)
        assert out.is_dir()


def test_explicit_fmt_name_wins_over_the_label(fake, client, tmp_path):
    ref = labelled(fake, "pics", "ultralytics", ultralytics_files(tmp_path))
    out = datasets.materialize(ref, tmp_path / "as-raw", fmt_name="raw", client=client)
    assert out.is_dir() and (out / "data.yaml").is_file()
    with pytest.raises(DatasetError, match="unknown dataset format"):
        datasets.materialize(ref, fmt_name="coco", client=client)


def test_prefix_is_rejected_by_ultralytics(fake, client, tmp_path):
    ref = labelled(fake, "pics", "ultralytics", ultralytics_files(tmp_path))
    with pytest.raises(DatasetError, match="only supported by the raw format"):
        datasets.materialize(ref, client=client, prefix="images")


def test_format_of(fake, client):
    labelled(fake, "pics", "yolo", {})
    labelled(fake, "plain", None, {})
    assert datasets.format_of("pics", client) == "ultralytics"
    assert datasets.format_of("plain", client) == "raw"
    assert datasets.format_of("does-not-exist", client) == "raw"


# ---- create --template none
def test_create_empty_dataset_only_kind_label_no_commit(fake, client):
    repo = datasets.create_dataset("mine", "none", "my files", client)
    assert repo == "dataset-mine"
    assert fake.repos[repo]["metadata"] == {"kaos.kind": "dataset", "kaos.description": "my files"}
    assert fake.tree(repo, "main") == {} and "commit_log" not in fake.repos[repo]


def test_cli_create_template_none_explains_next_steps(fake, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_connect", lambda args: fake.client())
    code = cli.main(["dataset", "create", "mine", "--template", "none", "--description", "d"])
    out = capsys.readouterr().out
    assert code == 0 and "empty, no template" in out
    assert "http://lakefs.test/repositories/dataset-mine/objects" in out
    assert "once its first commit lands" in out and "kubecore dataset push" in out
    assert fake.repos["dataset-mine"]["metadata"]["kaos.kind"] == "dataset"


# ---- CLI on any repository
@pytest.fixture
def use_fake(fake, monkeypatch):
    monkeypatch.setattr(cli, "_connect", lambda args: fake.client())


def test_cli_versions_and_pull_work_on_any_repository(fake, use_fake, capsys):
    fake.add_repo("my-repo", ns="gs://b/x/my-repo", files=FILES)
    fake.tag("my-repo", "v1")
    assert cli.main(["dataset", "versions", "my-repo"]) == 0
    assert "my-repo: v1" in capsys.readouterr().out
    assert cli.main(["dataset", "pull", "my-repo@v1"]) == 0
    assert "Ready:" in capsys.readouterr().out
    assert cli.main(["dataset", "pull", "my-repo@main", "--prefix", "sub"]) == 0
    assert "your files are in" in capsys.readouterr().out


def test_cli_push_without_template_label_validates_nothing(fake, use_fake, capsys, tmp_path):
    fake.add_repo("my-repo", ns="gs://b/x/my-repo")
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "notes.txt").write_text("hi")
    assert cli.main(["dataset", "push", str(junk), "my-repo", "-m", "files"]) == 0
    assert "/repositories/my-repo/pulls/1" in capsys.readouterr().out


def test_cli_push_with_ultralytics_label_validates(fake, use_fake, capsys, tmp_path):
    fake.add_repo("pics", ns="gs://b/x/pics", metadata={"kaos.template": "ultralytics"})
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "notes.txt").write_text("hi")
    assert cli.main(["dataset", "push", str(junk), "pics", "-m", "files"]) == 2
    assert "data.yaml is missing" in capsys.readouterr().err
