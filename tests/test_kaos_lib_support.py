"""The enhancer passes the kaos-lib support window to every step (PRD novelcore/kaos#1147).

pipeline-context kaosLib.support (the newest release's release.json) -> env KAOS_LIB_SUPPORT on
every step, and on the MeluXina twin, which forwards it to the Slurm job.
"""
import json

import yaml
from test_datasets_as_repos import CTX_PATH, _raw

from kubecore.enhance import enhance

SUPPORT = {"version": "0.4.0", "supported": ">=0.3", "deprecated": [{"range": "<0.3", "unsupported_after": "2027-01-01"}]}


def _env(out, name):
    t = next(t for t in out["spec"]["templates"] if t["name"] == name)
    return {e["name"]: e.get("value") for e in t["container"].get("env", [])}


def _ctx(support):
    ctx = yaml.safe_load(CTX_PATH.read_text())
    if support is not None:
        ctx["kaosLib"] = {"spec": "==0.4.0", "version": "0.4.0", "support": support}
    return ctx


def test_every_step_gets_the_support_window():
    out = enhance(_raw(), _ctx(SUPPORT))
    steps = [t["name"] for t in out["spec"]["templates"] if "container" in t and t["name"] != "hpc-follower"]
    checked = 0
    for name in steps:
        env = _env(out, name)
        if "CHECKPOINT_BUCKET" in env:  # a pipeline step (platform utility templates carry no step env)
            assert json.loads(env["KAOS_LIB_SUPPORT"]) == SUPPORT, name
            checked += 1
    assert checked == len(steps) >= 1, steps


def test_a_json_string_is_passed_as_it_is():
    raw = json.dumps(SUPPORT)
    assert _env(enhance(_raw(), _ctx(raw)), "model-training")["KAOS_LIB_SUPPORT"] == raw


def test_no_support_data_injects_nothing():
    assert "KAOS_LIB_SUPPORT" not in _env(enhance(_raw(), _ctx(None)), "model-training")


def test_the_meluxina_twin_carries_it_to_the_controller():
    assert json.loads(_env(enhance(_raw(), _ctx(SUPPORT)), "hpc-follower")["KAOS_LIB_SUPPORT"]) == SUPPORT


def test_a_developer_set_value_wins():
    raw = _raw()
    step = next(t for t in raw["spec"]["templates"] if t["name"] == "model-training")
    step["container"]["env"] = [{"name": "KAOS_LIB_SUPPORT", "value": "{}"}]
    assert _env(enhance(raw, _ctx(SUPPORT)), "model-training")["KAOS_LIB_SUPPORT"] == "{}"
