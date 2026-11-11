"""An app is pipeline.py, config/ and steps/. The platform runs the pipeline engine itself."""
from conftest import ROOT


def test_should_not_ship_a_copy_of_the_platform_pipeline_engine():
    assert not (ROOT / "kubecore").exists(), "the platform provides the engine: do not vendor kubecore/"


def test_should_not_ship_the_compose_step():
    assert not (ROOT / "steps" / "compose_and_validate").exists(), "the platform composes the run's params itself"
