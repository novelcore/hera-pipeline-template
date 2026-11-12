"""The guide of kaos-lib builds its first ten pages on this template, and shows its files from a copy.

Point DOCS_CHECK_KAOS_LIB at a checkout of kaos-lib to compare: the copy must equal this template byte for byte.
Without it the test is skipped.
"""
import os
from pathlib import Path

import pytest
from conftest import ROOT

LIB = os.environ.get("DOCS_CHECK_KAOS_LIB")
pytestmark = pytest.mark.skipif(not LIB, reason="set DOCS_CHECK_KAOS_LIB to a checkout of kaos-lib")


def shown(root: Path) -> set:
    files = {"pipeline.py", *(p.relative_to(root).as_posix() for p in (root / "config").glob("*.yaml"))}
    return files | {p.relative_to(root).as_posix() for p in (root / "steps").glob("*/app/entry.py")}


def test_should_equal_the_copy_the_guide_of_kaos_lib_shows():
    copy = Path(LIB) / "docs" / "examples" / "first-pipeline" / "template"
    assert shown(copy) == shown(ROOT), "the guide shows other files than this template holds"
    different = [name for name in sorted(shown(ROOT)) if (copy / name).read_bytes() != (ROOT / name).read_bytes()]
    assert not different, f"these files differ from docs/examples/first-pipeline/template of kaos-lib: {different}"
