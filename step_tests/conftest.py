"""Shared pieces of the step tests: the run's settings and `kaosctl step run`, which runs a step as the platform does."""
import shutil
import sys
from pathlib import Path

import pytest
import yaml

try:
    from kaos_lib import cli
except ImportError:
    raise pytest.UsageError("step tests need kaos-lib: see step_tests/README.md for the pip install line") from None

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".kaos" / "local"  # where `kaosctl step run` keeps what the steps wrote; never committed


@pytest.fixture(scope="session")
def params_file(tmp_path_factory) -> Path:
    """The run's settings: the defaults of every file in config/, as the platform composes them."""
    settings = {}
    for file in sorted((ROOT / "config").glob("*.yaml")):
        if file.name != "config.yaml":
            settings.update(yaml.safe_load(file.read_text()))
    path = tmp_path_factory.mktemp("params") / "params.yaml"
    path.write_text(yaml.safe_dump(settings))
    return path


@pytest.fixture(scope="session")
def run_step(params_file):
    """run_step("prepare", "--input", "dataset=<folder>") runs one step and returns its exit code."""
    for kept in ("results", "staged"):  # start clean: no result or output of an earlier run
        shutil.rmtree(LOCAL / kept, ignore_errors=True)
    return lambda step, *args: cli.main(["step", "run", step, str(ROOT), "--params-file", str(params_file), "--python", sys.executable, *args])
