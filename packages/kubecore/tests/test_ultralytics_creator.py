"""ultralytics creator: skeleton, validate (each error kind), publish through a pull request."""
import pytest
import yaml

from conftest import write_dataset
from kubecore import datasets
from kubecore.errors import DatasetError, ValidationFailed
from kubecore.formats import get_format
from kubecore.formats.ultralytics import validate

creator = get_format("ultralytics").creator


def test_skeleton_is_a_valid_layout():
    files = creator.skeleton(["cat", "dog"], "pets")
    data = yaml.safe_load(files["data.yaml"])
    assert data["nc"] == 2 and data["names"] == {0: "cat", 1: "dog"}
    assert (data["train"], data["val"], data["test"]) == ("images/train", "images/val", "images/test")
    for kind in ("images", "labels"):
        for split in ("train", "val", "test"):
            assert f"{kind}/{split}/.keep" in files
    assert "pets" in files["README.md"].decode()


def test_skeleton_needs_classes():
    with pytest.raises(DatasetError, match="at least one class"):
        creator.skeleton([" ", ""])


def test_validate_ok(dataset_dir):
    assert validate(dataset_dir).ok


def test_validate_accepts_list_style_names(dataset_dir):
    (dataset_dir / "data.yaml").write_text(
        "train: images/train\nval: images/val\nnc: 2\nnames: [a, b]\n")
    assert validate(dataset_dir).ok


def _errors(root):
    return "\n".join(validate(root).errors)


def test_validate_missing_data_yaml(tmp_path):
    assert "data.yaml is missing" in _errors(tmp_path)


def test_validate_nc_mismatch(dataset_dir):
    text = (dataset_dir / "data.yaml").read_text().replace("nc: 2", "nc: 3")
    (dataset_dir / "data.yaml").write_text(text)
    assert "nc is 3 but names has 2" in _errors(dataset_dir)


def test_validate_image_without_label(tmp_path):
    root = write_dataset(tmp_path / "d", skip_label=("train", "b"))
    assert "images/train/b.jpg has no label file labels/train/b.txt" in _errors(root)


@pytest.mark.parametrize("line,fragment", [
    ("0 0.5 0.5 0.2", "expected '<class-id> <x> <y> <w> <h>'"),
    ("5 0.5 0.5 0.2 0.2", "class id 5 is outside 0..1"),
    ("0 1.5 0.5 0.2 0.2", "coordinates must be within [0,1]"),
    ("x 0.5 0.5 0.2 0.2", "class id must be an integer"),
    ("0 0.5 abc 0.2 0.2", "class id must be an integer and x y w h numbers"),
])
def test_validate_label_line_errors(tmp_path, line, fragment):
    root = write_dataset(tmp_path / "d", bad_label=line)
    assert fragment in _errors(root)


def test_validate_aggregates_all_errors(tmp_path):
    root = write_dataset(tmp_path / "d", bad_label="9 2 2 2 2", skip_label=("val", "a"))
    errors = validate(root).errors
    assert len(errors) >= 3  # class id, coordinates, missing label
    assert "more" not in validate(root).format()


def test_validate_requires_train_and_val_images(tmp_path):
    root = write_dataset(tmp_path / "d")
    for f in (root / "images" / "val").iterdir():
        f.unlink()
    assert "images/val/ has no images" in _errors(root)


def test_publish_opens_pull_request_and_never_writes_main(fake, client, dataset_dir):
    result = creator.publish(dataset_dir, "dataset-default", "add images", client=client)
    assert result.branch.startswith("draft/") and result.pull_id == "1"
    assert result.pull_url == "http://lakefs.test/repositories/dataset-default/pulls/1"
    r = fake.repos["dataset-default"]
    assert r["pulls"][0]["source_branch"] == result.branch and r["pulls"][0]["destination_branch"] == "main"
    assert all(branch != "main" for _, _, branch, _ in fake.writes)       # uploads only on the draft
    assert [b for b, *_ in r["commit_log"]] == [result.branch]            # the only commit is on the draft
    assert fake.tree("dataset-default", "main") == {}                     # main untouched until the PR is merged
    assert "images/train/a.jpg" in fake.tree("dataset-default", result.branch)


def test_publish_creates_missing_repo_with_labels_then_pr(fake, client, dataset_dir):
    result = creator.publish(dataset_dir, "dataset-new", "first", description="d", client=client)
    assert result.created and result.pull_id
    assert fake.repos["dataset-new"]["metadata"] == {
        "kaos.kind": "dataset", "kaos.template": "ultralytics", "kaos.description": "d"}
    assert all(branch != "main" for _, _, branch, _ in fake.writes)


def test_publish_invalid_dataset_uploads_nothing(fake, client, tmp_path):
    root = write_dataset(tmp_path / "d", bad_label="0 9 9 9 9")
    with pytest.raises(ValidationFailed) as err:
        creator.publish(root, "dataset-default", "m", client=client)
    assert err.value.errors and fake.writes == []


def test_publish_is_idempotent_nothing_to_publish(fake, client, dataset_dir):
    first = creator.publish(dataset_dir, "dataset-default", "one", client=client)
    # merge the draft into main as a PR merge would
    r = fake.repos["dataset-default"]
    r["branches"]["main"]["commit"] = r["branches"][first.branch]["commit"]
    with pytest.raises(DatasetError, match="nothing to publish"):
        creator.publish(dataset_dir, "dataset-default", "two", client=client)


def test_publish_mirrors_deletions(fake, client, dataset_dir):
    r = fake.repos["dataset-default"]
    r["commits"]["c-old"] = {"images/train/gone.jpg": b"x"}
    r["branches"]["main"]["commit"] = "c-old"
    result = creator.publish(dataset_dir, "dataset-default", "m", client=client)
    assert "images/train/gone.jpg" not in fake.tree("dataset-default", result.branch)


def test_publish_direct_only_when_asked(fake, client, dataset_dir):
    result = creator.publish(dataset_dir, "dataset-default", "m", via_pull_request=False, client=client)
    assert result.branch == "main" and result.pull_id is None
    assert "data.yaml" in fake.tree("dataset-default", "main")
