"""The two example steps, one after the other: prepare writes the dataset `clean`, hello-world reads it."""
import json

import pytest
from conftest import LOCAL


def result(step: str) -> dict:
    return json.loads((LOCAL / "results" / f"{step}.json").read_text())


@pytest.fixture(scope="module")
def ran(tmp_path_factory, run_step):
    data = tmp_path_factory.mktemp("dataset")
    (data / "images").mkdir()
    (data / "images" / "a.txt").write_text("a")
    (data / "b.txt").write_text("b")
    (data / "empty.txt").write_text("")
    assert run_step("prepare", "--input", f"dataset={data}") == 0
    assert run_step("hello-world") == 0


def test_prepare_writes_the_files_that_are_not_empty_as_the_dataset_clean(ran):
    clean = LOCAL / "staged" / "clean"
    assert sorted(p.relative_to(clean).as_posix() for p in clean.rglob("*.txt")) == ["b.txt", "images/a.txt"]
    assert result("prepare")["values"] == {"files": 2, "dropped": 1}
    assert [(w["name"], w["type"], w["repo"]) for w in result("prepare")["writes"]] == [("clean", "dataset", "dataset-clean")]


def test_hello_world_reads_exactly_the_version_prepare_wrote(ran):
    written = result("prepare")["writes"][0]["commit"]
    assert [(r["name"], r["commit"]) for r in result("hello-world")["reads"]] == [("clean", written)]
    assert result("hello-world")["values"] == {"files": 2}
    report = (LOCAL / "staged" / "report" / "hello.txt").read_text()
    assert report.endswith(": 2 files in clean, 1 dropped by prepare\n")
