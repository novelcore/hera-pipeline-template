"""Every step gets everything from kaos_lib.step: no argument and no variable of its own."""
import pytest
from conftest import ROOT

ENTRIES = sorted((ROOT / "steps").glob("*/app/entry.py"))
NOT_IN_A_STEP = ("os.environ", "getenv", "argparse", "sys.argv")  # a step takes no arguments and reads no variable


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parts[-3])
def test_a_step_starts_with_the_step_api_and_ends_with_a_result_and_reads_no_variable(entry):
    text = entry.read_text()
    assert "step.start()" in text and "step.result(" in text
    assert not [word for word in NOT_IN_A_STEP if word in text]



def test_the_experiment_setting_holds_only_the_end_of_a_name_and_no_step_writes_a_name_of_its_own():
    """The project's MLflow takes an experiment or a model named `<app>` or `<app>.<x>` only: the setting is the `<x>`,
    and no step writes a name in the code (the app's name is `step.start().app`)."""
    import re

    import yaml
    name = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text())["experiment"]["name"]
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}", name), f"experiment.name {name!r} could not follow '<app>.'"
    for path in [*(ROOT / "steps").rglob("*.py"), *(ROOT / "examples").rglob("*.py")]:
        text = path.read_text()
        for call in re.findall(r"(?:set_experiment|create_experiment|register_model|create_registered_model)\(([^)]*)\)", text):
            assert not re.match(r"\s*['\"]", call), f"{path}: a name written in the code: {call}"
