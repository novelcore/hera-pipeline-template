"""The kaos-lib version the step images install.

The platform picks the version: its build passes --build-arg KAOS_LIB_PACKAGE=<requirement> to every step
image that declares the ARG, only inside the range in .kaos/compat.yaml.
"""
from importlib.metadata import version

import yaml
from conftest import ROOT
from packaging.specifiers import SpecifierSet

DOCKERFILES = sorted(ROOT.glob("steps/*/Dockerfile")) + [ROOT / "examples" / "gpu_check" / "Dockerfile"]
# The image has no default: the platform's build, `kaosctl step run` and `kaosctl dev` pass the requirement.
FAIL = "pass --build-arg KAOS_LIB_PACKAGE, or use kaosctl step run / kaosctl dev, which take your platform's choice"
EMPTY_ARG = 'ARG KAOS_LIB_PACKAGE=""'


def test_every_step_image_takes_the_platform_requirement_and_has_no_default():
    for dockerfile in DOCKERFILES:
        text = dockerfile.read_text()
        assert EMPTY_ARG in text.splitlines(), f"{dockerfile}: ARG KAOS_LIB_PACKAGE has no default"
        install = 'RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"'
        assert install in text
        guard = text.index("RUN test -n \"${KAOS_LIB_PACKAGE}\"")
        assert FAIL in text[guard:text.index(install)], f"{dockerfile}: an empty value must fail with a clear message"
        assert guard < text.index(install), f"{dockerfile}: the check comes before the install"


def test_the_app_declares_the_range_of_its_package():
    compat = yaml.safe_load((ROOT / ".kaos" / "compat.yaml").read_text())
    assert SpecifierSet(compat["kaos-lib"]).contains(version("kaos-lib"), prereleases=True), \
        "the installed kaos-lib is inside the range .kaos/compat.yaml declares"
