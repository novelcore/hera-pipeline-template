"""Shared references ``<owner>/dataset-<name>@<ref>``: parsing, round-trip, and the refusal of every write."""
import json

import pytest

from conftest import write_dataset
from kubecore import cli, datasets
from kubecore.errors import DatasetError
from kubecore.formats import get_format, local

parse = datasets.DatasetRef.parse


# ------------------------------------------------------------------ parse
@pytest.mark.parametrize("text,owner,repo,version", [
    ("a/dataset-x@v1", "a", "dataset-x", "v1"),
    ("e2e-mls-7f3/dataset-cats@latest", "e2e-mls-7f3", "dataset-cats", "latest"),
    ("a/dataset-x@v10", "a", "dataset-x", "v10"),
    ("a/dataset-x@3f1c9e2a7b44", "a", "dataset-x", "3f1c9e2a7b44"),    # a commit id
    ("a/dataset-x@feature/y", "a", "dataset-x", "feature/y"),          # a branch with a slash: '/' after '@' is the ref's
    ("0/dataset-x@v1", "0", "dataset-x", "v1"),                          # one-character owner
    ("a" * 63 + "/dataset-x@v1", "a" * 63, "dataset-x", "v1"),          # 63 characters: the maximum
    ("a-b-9/dataset-" + "n" * 55 + "@v2", "a-b-9", "dataset-" + "n" * 55, "v2"),   # 63-character repository
    ("a/dataset-ab@v1", "a", "dataset-ab", "v1"),
    ("  a/dataset-x@v1  ", "a", "dataset-x", "v1"),
])
def test_parse_shared_ref(text, owner, repo, version):
    ref = parse(text)
    assert (ref.owner, ref.repo, ref.version, ref.commit) == (owner, repo, version, None)


@pytest.mark.parametrize("text", ["a/dataset-x@v1", "a/dataset-x@latest", "a/dataset-x@c0ffee12",
                                  "dataset-x@v1", "my-repo@feature/x-1", "e2e-mls-1/dataset-default@v3"])
def test_round_trip(text):
    ref = parse(text)
    assert str(ref) == text and parse(str(ref)) == ref


def test_round_trip_keeps_the_owner_through_with_commit():
    pinned = parse("a/dataset-x@v1").with_commit("c0ffee12")
    assert (pinned.owner, pinned.repo, pinned.version, pinned.commit) == ("a", "dataset-x", "v1", "c0ffee12")
    assert str(pinned) == "a/dataset-x@v1"


@pytest.mark.parametrize("text,fragment", [
    ("A/dataset-x@v1", "'A' is not a project name"),                       # uppercase
    ("Ab/dataset-x@v1", "'Ab' is not a project name"),
    ("a" * 64 + "/dataset-x@v1", "is not a project name"),                  # 64 characters: too long
    ("-a/dataset-x@v1", "'-a' is not a project name"),                     # leading hyphen
    ("a-/dataset-x@v1", "'a-' is not a project name"),                     # trailing hyphen
    ("-/dataset-x@v1", "'-' is not a project name"),
    ("/dataset-x@v1", "'' is not a project name"),                         # empty owner
    ("a_b/dataset-x@v1", "'a_b' is not a project name"),
    ("a.b/dataset-x@v1", "'a.b' is not a project name"),
    ("a/b/c@v1", "more than one '/'"),
    ("a/dataset-x/c@v1", "more than one '/'"),
    ("a//dataset-x@v1", "more than one '/'"),
    ("a/my-repo@main", "a/my-repo is not a shared dataset"),               # owner + a non-dataset repository
    ("a/outputs-app@main", "a/outputs-app is not a shared dataset"),
    ("a/dataset-@v1", "a/dataset- is not a shared dataset"),               # no name after the prefix
    ("a/dataset@v1", "a/dataset is not a shared dataset"),
    ("a/xdataset-y@v1", "a/xdataset-y is not a shared dataset"),
    ("a/@v1", "a/ is not a shared dataset"),
    ("a/dataset-" + "n" * 56 + "@v1", "not a valid lakeFS repository name"),   # 64 characters
    ("a/dataset-X@v1", "not a valid lakeFS repository name"),
    ("a/dataset-x_y@v1", "not a valid lakeFS repository name"),
    ("a/dataset-x", "not a dataset reference"),                            # no ref
    ("a/dataset-x@", "not a dataset reference"),
    ("a/dataset-x@v1@v2", "more than one '@'"),
    ("a/dataset-x@bad ref", "not a valid ref"),
    ("a/dataset-x@a..b", "not a valid ref"),
])
def test_parse_invalid_shared_ref(text, fragment):
    with pytest.raises(DatasetError) as err:
        parse(text)
    assert fragment in str(err.value)


def test_owner_equal_to_the_own_project_is_normalised():
    ref = parse("b/dataset-x@v1", own_project="b")
    assert ref.owner is None and ref == parse("dataset-x@v1") and str(ref) == "dataset-x@v1"
    assert parse("a/dataset-x@v1", own_project="b").owner == "a"
    assert parse("dataset-x@v1", own_project="b").owner is None


def test_owner_normalisation_still_validates_the_repository():
    with pytest.raises(DatasetError, match="not a shared dataset"):
        parse("b/my-repo@main", own_project="b")


# ------------------------------------------------------------------ writes are refused before any network call
class NoNetwork:
    """A client stand-in that fails the test on any use."""

    def __getattr__(self, name):
        raise AssertionError(f"network used: {name}")


@pytest.mark.parametrize("call", [
    lambda: datasets.release("a/dataset-x", NoNetwork()),
    lambda: datasets.create_dataset("a/cats", "ultralytics", "", NoNetwork(), classes=["cat"]),
    lambda: datasets.create_dataset("a/cats", datasets.NO_TEMPLATE, "", NoNetwork()),
    lambda: datasets.publish_tree(".", "a/dataset-x", "m", client=NoNetwork()),
    lambda: get_format("raw").creator.publish(".", "a/dataset-x", "m", client=NoNetwork()),
])
def test_library_writes_of_owner_refs_are_refused(call):
    with pytest.raises(DatasetError, match="belongs to project a.*read-only"):
        call()


def test_ultralytics_push_of_an_owner_ref_is_refused_before_validation(tmp_path):
    bad = write_dataset(tmp_path / "bad", bad_label="7 0.5 0.5 0.1 0.1")       # would fail validation
    with pytest.raises(DatasetError, match="cannot push to a/dataset-x: it belongs to project a"):
        get_format("ultralytics").creator.publish(bad, "a/dataset-x", "m", client=NoNetwork())


@pytest.fixture
def no_connect(monkeypatch):
    def refuse(args):
        raise AssertionError("connected to lakeFS")
    monkeypatch.setattr(cli, "_connect", refuse)


@pytest.mark.parametrize("argv,fragment", [
    (["dataset", "release", "a/dataset-x"], "cannot release a/dataset-x: it belongs to project a"),
    (["dataset", "release", "a/dataset-x@v1"], "cannot release a/dataset-x@v1"),
    (["dataset", "push", ".", "a/dataset-x", "-m", "x"], "cannot push to a/dataset-x"),
    (["dataset", "push", ".", "a/dataset-x", "-m", "x", "--no-validate"], "cannot push to a/dataset-x"),
    (["dataset", "create", "a/cats", "--classes", "c"], "cannot create a/cats"),
    (["dataset", "create", "a/cats", "--template", "none"], "cannot create a/cats"),
])
def test_cli_writes_of_owner_refs_are_refused_before_connecting(capsys, no_connect, argv, fragment):
    code = cli.main(argv)
    err = capsys.readouterr().err
    assert code == 1 and err.startswith("ERROR:") and fragment in err and "read-only" in err
    assert "Traceback" not in err and err.count("\n") == 1


def test_refuse_shared_lets_own_names_through():
    for name in ("dataset-x", "x", "my-repo", "dataset-x@v1", "my-repo@feature/x"):
        datasets.refuse_shared(name, "release")   # no '/' before '@': the own project


# ------------------------------------------------------------------ cache path, marker, staged copy
def test_cache_dir_puts_shared_copies_under_the_owner(tmp_path):
    root = tmp_path / "cache"
    assert local.cache_dir("dataset-x", "c1") == root / "dataset-x" / "c1"
    assert local.cache_dir("dataset-x", "c1", owner="a") == root / "a" / "dataset-x" / "c1"
    assert local.cache_dir("dataset-x", "c1", "sub/", "a").parent == root / "a" / "dataset-x"
    assert local.cache_dir("dataset-x", "c1", owner="a") != local.cache_dir("dataset-x", "c1", owner="b")


def test_marker_must_match_the_owner(tmp_path):
    d = tmp_path / "copy"
    d.mkdir()
    (d / local.MARKER).write_text(json.dumps({"repo": "dataset-x", "commit": "c1", "prefix": None, "owner": "a"}))
    assert local.marker_matches(d, "dataset-x", "c1", owner="a")
    assert not local.marker_matches(d, "dataset-x", "c1")                 # the own dataset-x
    assert not local.marker_matches(d, "dataset-x", "c1", owner="b")
    (d / local.MARKER).write_text(json.dumps({"repo": "dataset-x", "commit": "c1", "prefix": None}))  # 0.1 marker
    assert local.marker_matches(d, "dataset-x", "c1") and not local.marker_matches(d, "dataset-x", "c1", owner="a")


@pytest.mark.parametrize("record,repo,owner,used", [
    ("", "dataset-x", None, True),                                              # no record: commit decides
    ("", "dataset-x", "a", False),                                              # shared: the record must name the owner
    ({"repo": "dataset-x", "commit": "c1"}, "dataset-x", None, True),
    ({"repo": "dataset-y", "commit": "c1"}, "dataset-x", None, False),          # another repository
    ({"repo": "dataset-x", "commit": "c1"}, "dataset-x", "a", False),           # the own dataset-x, not a's
    ({"repo": "dataset-x", "commit": "c1", "owner": "a"}, "dataset-x", "a", True),
    ({"repo": "dataset-x", "commit": "c1", "owner": "a"}, "dataset-x", None, False),
    ({"repo": "dataset-x", "commit": "c1", "owner": "a"}, "dataset-x", "b", False),
    ({"repo": "dataset-y", "commit": "c1", "owner": "a"}, "dataset-x", "a", False),
])
def test_staged_dir_checks_repository_and_owner(tmp_path, monkeypatch, record, repo, owner, used):
    staged = tmp_path / "lustre" / "c1"
    staged.mkdir(parents=True)
    (staged / ".kaos-ready").write_text(record if isinstance(record, str) else json.dumps(record))
    monkeypatch.setenv("KUBECORE_STAGED_DIR", str(staged))
    assert (local.staged_dir("c1", repo=repo, owner=owner) == staged) is used
    assert local.staged_dir("c2", repo=repo, owner=owner) is None             # another commit: never
