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

