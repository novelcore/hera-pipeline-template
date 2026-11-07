"""PRD-HPC-1461 D-44 as amended 2026-11-05: authoring and render of ``step(..., resumable=True | "20m")``.

* Only a step declared resumable gets a lead before the wall time (the stop signal), and its twin gets
  a deadline that covers every continuation.
* A lead that is not shorter than the wall time is refused at render.

The signal handling, checkpoint stage-out and continuation themselves run in the HPC controller's
runner (PRD-HPC-1461 F-35 retired the in-pod copies and their tests).
Run:  python -m pytest tests/ -v
"""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------- authoring and render

def _render(**kw):
    from kubecore import authoring, enhance
    with authoring.pipeline("t") as p:
        authoring.step("train", gpu=True, **kw)
    ctx = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())
    wft = enhance.enhance(yaml.safe_load(p.wt.to_yaml()), ctx)
    for t in wft["spec"]["templates"]:
        for task in (t.get("dag") or {}).get("tasks") or []:
            if task["name"] == "train-meluxina":
                return {a["name"]: a["value"] for a in task["arguments"]["parameters"]}
    raise AssertionError("no HPC twin rendered")


@pytest.mark.parametrize("value, lead", [(True, "10m"), ("20m", "20m"), ("1h", "1h"), ("15", "15")])
def test_resumable_is_an_annotation(value, lead):
    from kubecore import authoring
    with authoring.pipeline("t") as p:
        authoring.step("train", gpu=True, resumable=value)
    (tmpl,) = [t for t in yaml.safe_load(p.wt.to_yaml())["spec"]["templates"] if t["name"] == "train"]
    assert tmpl["metadata"]["annotations"][authoring.HPC_RESUMABLE_ANNOTATION] == lead


@pytest.mark.parametrize("value", ["0m", "00", "soon", 10, "10s"])
def test_a_bad_lead_is_refused(value):
    from kubecore import authoring
    with pytest.raises(authoring.AuthoringError), authoring.pipeline("t"):
        authoring.step("train", gpu=True, resumable=value)


def test_resumable_needs_a_gpu_step():
    from kubecore import authoring
    with pytest.raises(authoring.AuthoringError), authoring.pipeline("t"):
        authoring.step("prep", resumable=True)


def test_a_resumable_steps_follower_gets_its_lead_and_a_deadline_for_every_continuation():
    from kubecore import meluxina
    one_job = (120 + meluxina.QUEUE_ALLOWANCE_MINUTES) * 60
    all_jobs = (1 + meluxina.HPC_MAX_CONTINUATIONS) * one_job
    plain = _render(hpc_time_limit="2h")      # not declared: resumability is discovered, so it may continue
    assert plain["resumable-lead"] == "0"
    assert int(plain["deadline-seconds"]) == all_jobs
    opted_out = _render(hpc_time_limit="2h", resumable=False)
    assert int(opted_out["deadline-seconds"]) == one_job
    resumable = _render(hpc_time_limit="2h", resumable="20m")
    assert resumable["resumable-lead"] == "20"
    assert int(resumable["deadline-seconds"]) == \
        (1 + meluxina.HPC_MAX_CONTINUATIONS) * (120 + meluxina.QUEUE_ALLOWANCE_MINUTES) * 60


def test_idle_timeout_reaches_the_follower_as_minutes_and_unset_leaves_the_platform_default():
    """step(idle_timeout=...) -> annotation (minutes, "0" = off) -> twin argument idle-timeout ->
    HPC_IDLE_TIMEOUT_MINUTES on the follower -> HPCArgoWorkflowJob spec.idleTimeoutMinutes. Unset: ""."""
    assert _render()["idle-timeout"] == ""
    assert _render(idle_timeout=40)["idle-timeout"] == "40"
    assert _render(idle_timeout="1h")["idle-timeout"] == "60"
    assert _render(idle_timeout=0)["idle-timeout"] == "0"
    assert _render(idle_timeout=False)["idle-timeout"] == "0"


def test_a_lead_not_shorter_than_the_wall_time_is_refused():
    with pytest.raises(ValueError, match="not shorter than its wall time"):
        _render(hpc_time_limit="30m", resumable="30m")


def test_resumable_false_is_the_opt_out_the_follower_passes_on_as_hpc_resumable_zero():
    """resumable=False -> annotation "off" -> twin argument resumable="0" -> HPC_RESUMABLE=0 on the follower,
    which the controller maps to HPCArgoWorkflowJob spec.resumableOptOut. Unset leaves "auto" (discovered)."""
    from kubecore import authoring
    assert _render(resumable=False)["resumable"] == "0"
    assert _render(resumable=False)["resumable-lead"] == "0"
    assert _render()["resumable"] == "auto"
    assert _render(resumable="20m")["resumable"] == "auto"
    with authoring.pipeline("t") as p:
        authoring.step("train", gpu=True, resumable=False)
    (tmpl,) = [t for t in yaml.safe_load(p.wt.to_yaml())["spec"]["templates"] if t["name"] == "train"]
    assert tmpl["metadata"]["annotations"][authoring.HPC_RESUMABLE_ANNOTATION] == "off"


def test_resumable_false_is_accepted_on_a_cpu_step():
    from kubecore import authoring
    with authoring.pipeline("t"):
        authoring.step("prep", resumable=False)
