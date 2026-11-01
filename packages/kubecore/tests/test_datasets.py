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
    ("x@v1", "not a dataset repository"),
    ("dataset-Ab@v1", "not a dataset repository"),
    ("dataset-ab@v1", "not a dataset repository"),   # 2 chars: below the 3-char minimum
    ("dataset-xyz@1", "not a version"),
    ("dataset-xyz@v0", "not a version"),
    ("dataset-xyz@main", "not a version"),
])
def test_parse_malformed_gives_clear_error(text, fragment):
    with pytest.raises(DatasetError) as err:
        datasets.DatasetRef.parse(text)
    assert fragment in str(err.value)


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
    assert r["ns"] == "gs://bucket/proj/dataset-cats"          # sibling of an existing repo's storage
    tree = fake.tree(repo, "main")
    assert {"data.yaml", "README.md", "images/train/.keep", "labels/test/.keep"} <= set(tree)


def test_create_dataset_existing_repo_is_an_error(fake, client):
    with pytest.raises(DatasetError, match="already exists"):
        datasets.create_dataset("default", "ultralytics", "", client, classes=["a"])


def test_get_format_alias_and_unknown():
    assert get_format("yolo") is get_format("ultralytics")
    with pytest.raises(DatasetError, match="unknown dataset format"):
        get_format("coco")
