"""The two example steps. Each is called in this process with `kaos_lib.testing.running`; one test runs both
one after the other through `kaosctl step run`, the way the platform runs them."""
import importlib.util
import json

from conftest import LOCAL, ROOT
from kaos_lib import testing


def entry(step_folder: str):
    spec = importlib.util.spec_from_file_location(f"{step_folder}_entry", ROOT / "steps" / step_folder / "app" / "entry.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dataset_of(root, **files):
    root.mkdir()
    for name, text in files.items():
        (root / name).write_text(text)
    return root


def test_prepare_keeps_the_files_that_are_not_empty_in_the_dataset_clean(tmp_path):
    data = dataset_of(tmp_path / "data", **{"b.txt": "b", "empty.txt": ""})
    (data / "images").mkdir()
    (data / "images" / "a.txt").write_text("a")
    with testing.running(tmp_path, kind="transform", params={"prepare": {"min_bytes": 1}}, inputs={"dataset": data},
                         produces=[("dataset", "clean")]) as run:
        entry("prepare").main()
    clean = run.output("clean")
    assert sorted(p.relative_to(clean).as_posix() for p in clean.rglob("*.txt")) == ["b.txt", "images/a.txt"]
    assert run.result["values"] == {"files": 2, "dropped": 1}


def test_hello_world_reports_the_files_of_the_dataset_prepare_wrote(tmp_path):
    clean = dataset_of(tmp_path / "clean", **{"a.txt": "a", "b.txt": "b"})
    with testing.running(tmp_path, kind="evaluate", experiment="exp", upstream={"prepare": {"files": 2, "dropped": 1}},
                         upstream_writes={"prepare": {"clean": clean}}, produces=[("artifact", "report")]) as run:
        entry("hello_world").main()
    assert run.result["values"] == {"files": 2}
    assert (run.output("report") / "hello.txt").read_text() == "exp: 2 files in clean, 1 dropped by prepare\n"


def test_kaosctl_step_run_runs_prepare_then_hello_world_on_the_version_prepare_wrote(tmp_path, run_step):
    data = dataset_of(tmp_path / "data", **{"b.txt": "b", "empty.txt": ""})
    assert run_step("prepare", "--input", f"dataset={data}") == 0
    assert run_step("hello-world") == 0
    result = lambda step: json.loads((LOCAL / "results" / f"{step}.json").read_text())  # noqa: E731
    written = result("prepare")["writes"][0]
    assert (written["name"], written["type"]) == ("clean", "dataset")
    assert written["repo"].startswith("dataset-") and written["repo"].endswith("-clean")
    assert [(r["name"], r["commit"]) for r in result("hello-world")["reads"]] == [("clean", written["commit"])]
    assert (LOCAL / "staged" / "report" / "hello.txt").read_text().endswith(": 1 files in clean, 1 dropped by prepare\n")
