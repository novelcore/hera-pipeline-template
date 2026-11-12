"""The kaos-lib version the step images install.

The platform picks the version: its build passes --build-arg KAOS_LIB_PACKAGE=<requirement> to every step
image that declares the ARG, only inside the range in .kaos/compat.yaml.
"""
import re
from importlib.metadata import version

import yaml
from conftest import ROOT

DOCKERFILES = sorted(ROOT.glob("steps/*/Dockerfile")) + [ROOT / "examples" / "gpu_check" / "Dockerfile"]
# The ARG holds the whole requirement: name[extras] then ==X.Y.Z or " @ <url>".
SPEC_RE = re.compile(r'^ARG KAOS_LIB_PACKAGE="(kaos-lib\[zitadel\](?: ?==\S+| @ https://\S+))"$', re.M)


def test_every_step_image_takes_the_platform_requirement_and_has_the_same_default():
    specs = set()
    for dockerfile in DOCKERFILES:
        text = dockerfile.read_text()
        assert SPEC_RE.search(text), f"{dockerfile}: ARG KAOS_LIB_PACKAGE with a ==X.Y.Z or @ <url> default"
        assert 'RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"' in text
        specs.add(SPEC_RE.search(text).group(1))
    assert len(specs) == 1, specs


def test_the_template_declares_the_range_of_its_package():
    compat = yaml.safe_load((ROOT / ".kaos" / "compat.yaml").read_text())
    assert compat == {"kaos-lib": ">=0.5,<0.6"}
    assert version("kaos-lib").startswith("0.5."), "the installed package is inside the declared range"
