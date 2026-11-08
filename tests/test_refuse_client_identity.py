"""PRD-HPC-1461 D-79 F-37: the enhancer refuses a raw WorkflowTemplate that picks its own service account,
patches its pod spec or takes a name the platform reserves, so a pipeline.py cannot run as `hpc-submitter`.
Run:  python -m pytest tests/test_refuse_client_identity.py -v
"""
import copy
import runpy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kubecore import enhance  # noqa: E402

CTX = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())


def _raw():
    ns = runpy.run_path(str(ROOT / "pipeline.py"), run_name="__pipeline__")
    return yaml.safe_load(ns["p"].wt.to_yaml())


def _first_container_template(wft):
    return next(t for t in wft["spec"]["templates"] if "container" in t)


def _set_spec(key, value):
    return lambda w: w["spec"].__setitem__(key, value)


def _set_tpl(key, value):
    return lambda w: _first_container_template(w).__setitem__(key, value)


def _rename_tpl(name):
    return lambda w: _first_container_template(w).__setitem__("name", name)


CASES = [
    ("should_refuse_spec_service_account_hpc_submitter", _set_spec("serviceAccountName", "hpc-submitter"),
     "service account"),
    ("should_refuse_spec_service_account_any_value", _set_spec("serviceAccountName", "default"), "service account"),
    ("should_refuse_template_service_account", _set_tpl("serviceAccountName", "hpc-submitter"), "service account"),
    ("should_refuse_template_executor_service_account", _set_tpl("executor", {"serviceAccountName": "hpc-submitter"}),
     "service account"),
    ("should_refuse_spec_pod_spec_patch", _set_spec("podSpecPatch", "serviceAccountName: hpc-submitter"),
     "podSpecPatch"),
    ("should_refuse_template_pod_spec_patch", _set_tpl("podSpecPatch", "serviceAccountName: hpc-submitter"),
     "podSpecPatch"),
    ("should_refuse_template_named_hpc_follower", _rename_tpl("hpc-follower"), "reserves"),
    ("should_refuse_template_named_legacy_meluxina_run", _rename_tpl("meluxina-run"), "reserves"),
]


@pytest.mark.parametrize("mutate,fragment", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_refuses_client_identity(mutate, fragment):
    wft = _raw()
    mutate(wft)
    with pytest.raises(enhance.EnhanceError) as err:
        enhance.enhance(wft, copy.deepcopy(CTX))
    assert fragment in str(err.value)


def test_should_name_the_offending_step_in_the_message():
    wft = _raw()
    tpl = _first_container_template(wft)
    tpl["serviceAccountName"] = "x"
    with pytest.raises(enhance.EnhanceError, match=tpl["name"]):
        enhance.enhance(wft, copy.deepcopy(CTX))


def test_should_accept_the_unmodified_pipeline_and_stay_idempotent():
    first = enhance.enhance(_raw(), copy.deepcopy(CTX))
    second = enhance.enhance(_raw(), copy.deepcopy(CTX))
    assert first == second
    # The platform's own account, set after the refusal, is not what is refused.
    assert first["spec"]["serviceAccountName"] == CTX["serviceAccountName"]
