"""The kaos-lib version the step images run (PRD novelcore/kaos#1147 package delivery).

The platform picks the version: CI passes --build-arg KAOS_LIB_PACKAGE=<spec> to every step
image that declares the ARG, only inside the range in .kaos/compat.yaml. Each step logs
`kaos-lib <version>` first, so a run's log names what it ran.
"""
import json
import re
from importlib.metadata import version
from pathlib import Path

import pytest
import yaml
from conftest import ROOT, load_step

PACKAGE_STEPS = ["dataset_loading", "hello_world"]  # compose_and_validate runs the vendored engine
# The ARG holds the whole requirement: name[extras] then ==X.Y.Z or " @ <url>".
SPEC_RE = re.compile(r'^ARG KAOS_LIB_PACKAGE="([A-Za-z0-9._-]+(?:\[[A-Za-z0-9,._-]+\])?(?: ?==\S+| @ https://\S+))"$', re.M)
PARAMS = yaml.safe_dump({"experiment": {"name": "exp1"}, "dataset": "dataset-default@v1"})
INSTALLED = version("kaos-lib")  # the installed package (kaos-io/kaos-lib), as the step images pin it


@pytest.mark.parametrize("step", PACKAGE_STEPS)
def test_every_package_step_takes_the_platform_spec(step):
    text = (ROOT / "steps" / step / "Dockerfile").read_text()
    assert SPEC_RE.search(text), "ARG KAOS_LIB_PACKAGE with a ==X.Y.Z or @ <url> default"
    assert 'RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"' in text
    assert SPEC_RE.search(text).group(1).startswith("kaos-lib[zitadel] @ "), "the default names the package and its extras"
    assert "KUBECORE_PKG_COMMIT" not in text


def test_every_step_installs_the_same_default():
    specs = {SPEC_RE.search((ROOT / "steps" / s / "Dockerfile").read_text()).group(1) for s in PACKAGE_STEPS}
    assert len(specs) == 1, specs


def test_the_template_declares_the_range_of_its_package():
    compat = yaml.safe_load((ROOT / ".kaos" / "compat.yaml").read_text())
    assert compat == {"kaos-lib": ">=0.4.0rc1,<0.5"}
    assert INSTALLED.startswith("0.4."), "the pinned package is inside the declared range"


def test_dataset_loading_logs_the_kaos_lib_version_first(monkeypatch, tmp_path, capsys):
    step = load_step("dataset_loading")
    monkeypatch.setattr(step, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(step, "pin", lambda dataset, client=None: {"dataset": dataset, "dataset_commit": "c1"})
    monkeypatch.setattr("sys.argv", ["entry", "--params", PARAMS])
    step.main()
    assert capsys.readouterr().out.splitlines()[0] == f"kaos-lib {INSTALLED}"


def test_hello_world_logs_the_kaos_lib_version_first(monkeypatch, capsys):
    step = load_step("hello_world")
    monkeypatch.setattr(step, "read_dataset", lambda info: Path("."))
    monkeypatch.setattr(step, "write_result", lambda cfg, info, entry: "c2")
    info = json.dumps({"dataset": "dataset-default@v1", "dataset_commit": "c1"})
    monkeypatch.setattr("sys.argv", ["entry", "--params", PARAMS, "--dataset-info", info])
    step.main()
    assert capsys.readouterr().out.splitlines()[0] == f"kaos-lib {INSTALLED}"


def test_the_version_follows_the_distribution_after_the_rename(monkeypatch):
    step = load_step("hello_world")

    def renamed(dist):
        if dist == "kaos-lib":
            return "0.3.0"
        raise step.PackageNotFoundError(dist)

    monkeypatch.setattr(step, "version", renamed)
    assert step.kaos_lib_version() == "0.3.0"
