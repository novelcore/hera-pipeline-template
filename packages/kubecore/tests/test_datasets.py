"""DatasetRef parsing, resolve, listing, versions and release numbering."""
import pytest

from kubecore import datasets
from kubecore.errors import DatasetError
from kubecore.formats import get_format


@pytest.mark.parametrize("text,repo,version", [
    ("dataset-xyz@v2", "dataset-xyz", "v2"),
    ("dataset-default@latest", "dataset-default", "latest"),
    (" dataset-a-b-1@v10 ", "dataset-a-b-1", "v10"),
])
def test_parse_valid(text, repo, version):
    ref = datasets.DatasetRef.parse(text)
    assert (ref.repo, ref.version) == (repo, version)
    assert str(ref) == f"{repo}@{version}"


@pytest.mark.parametrize("text,fragment", [
    ("", "not a dataset reference"),
    ("dataset-xyz", "not a dataset reference"),
    ("dataset-xyz@", "not a dataset reference"),
    ("@v1", "not a dataset reference"),
    ("dataset-xyz@v1@v2", "more than one '@'"),
    ("x@v1", "not a valid lakeFS repository name"),
    ("ab@v1", "not a valid lakeFS repository name"),   # 2 chars: below the 3-char minimum
    ("Dataset-Ab@v1", "not a valid lakeFS repository name"),
    ("-bad-start@v1", "not a valid lakeFS repository name"),
    ("my_repo@main", "not a valid lakeFS repository name"),
    ("dataset-xyz@bad ref", "not a valid ref"),
    ("dataset-xyz@a..b", "not a valid ref"),
    ("dataset-xyz@-x", "not a valid ref"),
    ("dataset-xyz@dir/", "not a valid ref"),
])
def test_parse_malformed_gives_clear_error(text, fragment):
    with pytest.raises(DatasetError) as err:
        datasets.DatasetRef.parse(text)
    assert fragment in str(err.value)


@pytest.mark.parametrize("text,repo,version", [
    ("dataset-default@latest", "dataset-default", "latest"),       # head of the default branch
    ("dataset-default@v3", "dataset-default", "v3"),                # tag
    ("my-lake-repo@main", "my-lake-repo", "main"),                  # any repository, a branch
    ("my-lake-repo@feature/x-1", "my-lake-repo", "feature/x-1"),    # branch with a slash
    ("my-lake-repo@release-2024.1", "my-lake-repo", "release-2024.1"),  # tag
    ("abc@3f1c9e2a7b", "abc", "3f1c9e2a7b"),                        # commit id
])
def test_parse_accepts_every_ref_kind_on_any_repository(text, repo, version):
    ref = datasets.DatasetRef.parse(text)
    assert (ref.repo, ref.version) == (repo, version) and str(ref) == text


def test_resolve_branch_tag_and_commit_on_a_non_dataset_repo(fake):
    client = fake.client()
    c1 = fake.add_repo("my-repo", ns="gs://b/x/my-repo")
    fake.repos["my-repo"]["commits"]["c2commit"] = {"a": b"1"}
    fake.repos["my-repo"]["branches"]["dev"] = {"commit": "c2commit", "base": c1, "staged": {}}
    fake.tag("my-repo", "rc1", "dev")
    parse = datasets.DatasetRef.parse
    assert datasets.resolve(parse("my-repo@latest"), client) == c1             # default branch head
    assert datasets.resolve(parse("my-repo@dev"), client) == "c2commit"        # branch
    assert datasets.resolve(parse("my-repo@rc1"), client) == "c2commit"        # tag
    assert datasets.resolve(parse("my-repo@c2commit"), client) == "c2commit"   # commit id
    with pytest.raises(DatasetError, match="no branch, tag or commit 'nope'"):
        datasets.resolve(parse("my-repo@nope"), client)


def test_latest_follows_a_non_main_default_branch(fake):
    client = fake.client()
    fake.add_repo("my-repo")
    fake.repos["my-repo"]["default_branch"] = "trunk"
    fake.repos["my-repo"]["commits"]["ctrunk"] = {}
    fake.repos["my-repo"]["branches"]["trunk"] = {"commit": "ctrunk", "base": "ctrunk", "staged": {}}
    assert datasets.resolve(datasets.DatasetRef.parse("my-repo@latest"), client) == "ctrunk"


def test_dataset_repo_normalizes_and_validates():
    assert datasets.dataset_repo("cats") == "dataset-cats"
    assert datasets.dataset_repo("dataset-cats") == "dataset-cats"
    for bad in ("ab", "Cats", "a" * 49, "has_underscore"):
        with pytest.raises(DatasetError):
            datasets.dataset_repo(bad)


def test_resolve_latest_is_main_head_and_version_is_tag_commit(fake, client):
    first = fake.head("dataset-default")
    fake.tag("dataset-default", "v1")
    fake.repos["dataset-default"]["commits"]["new"] = {"x": b"1"}
    fake.repos["dataset-default"]["branches"]["main"]["commit"] = "new"
    assert datasets.resolve(datasets.DatasetRef.parse("dataset-default@v1"), client) == first
    assert datasets.resolve(datasets.DatasetRef.parse("dataset-default@latest"), client) == "new"


def test_resolve_unknown_version_lists_available(fake, client):
    fake.tag("dataset-default", "v1")
    with pytest.raises(DatasetError) as err:
        datasets.resolve(datasets.DatasetRef.parse("dataset-default@v7"), client)
    assert "no version v7" in str(err.value) and "v1" in str(err.value)


def test_resolve_unknown_repo(client):
    with pytest.raises(DatasetError, match="does not exist"):
        datasets.resolve(datasets.DatasetRef.parse("dataset-nope@v1"), client)


def test_list_datasets_only_dataset_repos_with_labels(fake, client):
    rows = datasets.list_datasets(client)
    assert [r.repo for r in rows] == ["dataset-default"]
    assert rows[0].default and rows[0].template == "ultralytics"


def test_versions_sorted_numerically(fake, client):
    for t in ("v10", "v2", "v1", "not-a-version"):
        fake.tag("dataset-default", t)
    assert datasets.versions("dataset-default", client) == ["v1", "v2", "v10"]


def test_release_first_is_v1_and_tags_main_head(fake, client):
    assert datasets.release("dataset-default", client) == "v1"
    assert fake.repos["dataset-default"]["tags"]["v1"] == fake.head("dataset-default")


def test_release_numbers_v10_after_v9(fake, client):
    for n in range(1, 10):
        fake.tag("dataset-default", f"v{n}", fake.head("dataset-default"))
    fake.repos["dataset-default"]["commits"]["newer"] = {"f": b"1"}
    fake.repos["dataset-default"]["branches"]["main"]["commit"] = "newer"
    assert datasets.release("dataset-default", client) == "v10"


def test_release_refuses_when_head_already_released(fake, client):
    datasets.release("dataset-default", client)
    with pytest.raises(DatasetError, match="already v1"):
        datasets.release("dataset-default", client)


def test_create_dataset_makes_labelled_repo_with_skeleton_on_main(fake, client):
    repo = datasets.create_dataset("cats", "yolo", "cat photos", client, classes=["cat", "dog"])
    r = fake.repos[repo]
    assert repo == "dataset-cats"
    assert r["metadata"] == {"kaos.kind": "dataset", "kaos.template": "ultralytics",
                             "kaos.description": "cat photos"}
    assert r["ns"] == "gs://bucket/lakefs/dataset-cats"        # <prefix kaos-lake publishes>/<repo>
    tree = fake.tree(repo, "main")
    assert {"data.yaml", "README.md", "images/train/.keep", "labels/test/.keep"} <= set(tree)


def test_create_dataset_existing_repo_is_an_error(fake, client):
    with pytest.raises(DatasetError, match="already exists"):
        datasets.create_dataset("default", "ultralytics", "", client, classes=["a"])


def test_get_format_alias_and_unknown():
    assert get_format("yolo") is get_format("ultralytics")
    with pytest.raises(DatasetError, match="unknown dataset format"):
        get_format("coco")


def test_create_dataset_follows_the_kaos_lake_ui_flow(fake, client):
    """repo -> starter files committed to main (commit metadata kaos.template) -> labels."""
    datasets.create_dataset("cats", "ultralytics", "d", client, classes=["cat"])
    seq = [(m, p.rsplit("/", 1)[-1]) for m, p in fake.calls if m == "POST" and "dataset-cats" in p or
           (m, p) == ("POST", "/repositories")]
    kinds = [p for _, p in seq]
    assert kinds.index("repositories") < kinds.index("commits") < kinds.index("metadata")
    branch, _, _, meta = fake.repos["dataset-cats"]["commit_log"][0]
    assert branch == "main" and meta == {"kaos.template": "ultralytics"}


def test_storage_prefix_falls_back_to_env_then_errors(fake, client, monkeypatch):
    fake.storage_prefix = None
    with pytest.raises(DatasetError, match="KUBECORE_STORAGE_NAMESPACE_BASE"):
        datasets.create_dataset("cats", "ultralytics", "", client, classes=["a"])
    assert "dataset-cats" not in fake.repos
    monkeypatch.setenv("KUBECORE_STORAGE_NAMESPACE_BASE", "gs://other/lake/")
    datasets.create_dataset("cats", "ultralytics", "", client, classes=["a"])
    assert fake.repos["dataset-cats"]["ns"] == "gs://other/lake/dataset-cats"


def test_published_storage_prefix_wins_over_env(fake, client, monkeypatch):
    monkeypatch.setenv("KUBECORE_STORAGE_NAMESPACE_BASE", "gs://other/lake")
    datasets.create_dataset("cats", "ultralytics", "", client, classes=["a"])
    assert fake.repos["dataset-cats"]["ns"] == "gs://bucket/lakefs/dataset-cats"
