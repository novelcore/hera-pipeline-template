"""Smoke test: the template renders + enhances to a valid WorkflowTemplate.

Sanity check that ships with the template — pipeline.py builds, the config tree
composes, and the enhancer produces a runnable WFT with the example hello-world
step. Run:  python -m pytest tests/ -v
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kaos_pipeline import enhance  # noqa: E402

CONTEXT = yaml.safe_load((ROOT / "kaos_pipeline" / "local-dev" / "pipeline-context.yaml").read_text())


def _render():
    import runpy
    ns = runpy.run_path(str(ROOT / "pipeline.py"), run_name="__pipeline__")
    return yaml.safe_load(ns["p"].wt.to_yaml())


def _enhanced():
    return enhance.enhance(_render(), CONTEXT)


def test_pipeline_renders():
    raw = _render()
    assert raw["kind"] == "WorkflowTemplate"
    assert raw["spec"]["templates"]


def test_enhance_produces_hello_world():
    steps = [t["name"] for t in _enhanced()["spec"]["templates"] if "container" in t]
    assert "hello-world" in steps
    assert "compose-and-validate" in steps


def test_config_tree_becomes_form():
    params = {p["name"] for p in _enhanced()["spec"].get("arguments", {}).get("parameters", [])}
    assert "experiment-name" in params


def test_dataset_is_a_form_parameter_the_platform_can_fill_with_choices():
    """The chart step hera-enhance-commit sets the enum of a parameter named exactly `dataset`."""
    params = {p["name"]: p for p in _enhanced()["spec"]["arguments"]["parameters"]}
    assert params["dataset"]["value"] == "dataset-default@latest"
    assert "data-ref" not in params


def test_dataset_loading_pins_the_dataset_for_the_steps_after_it():
    wft = _enhanced()
    tasks = {t["name"]: t for t in next(x for x in wft["spec"]["templates"] if "dag" in x)["dag"]["tasks"]}
    assert "dataset-loading" in tasks["hello-world"]["depends"]
    names = {p["name"] for p in tasks["hello-world"]["arguments"]["parameters"]}
    assert "dataset-info" in names
    loading = next(t for t in wft["spec"]["templates"] if t["name"] == "dataset-loading")
    assert [o["name"] for o in loading["outputs"]["parameters"]] == ["dataset-info"]
