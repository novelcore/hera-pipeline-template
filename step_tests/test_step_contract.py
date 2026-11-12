"""Every step is short and gets everything from kaos_lib.step."""
import pytest
from conftest import ROOT

ENTRIES = sorted((ROOT / "steps").glob("*/app/entry.py"))
NOT_IN_A_STEP = ("os.environ", "getenv", "argparse", "sys.argv")  # a step takes no arguments and reads no variable


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parts[-3])
def test_an_example_step_is_at_most_25_lines_and_reads_nothing_but_the_step_api(entry):
    text = entry.read_text()
    assert len(text.splitlines()) <= 25
    assert "step.start()" in text and "step.result(" in text
    assert not [word for word in NOT_IN_A_STEP if word in text]

