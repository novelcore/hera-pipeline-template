"""The MeluXina twin is retried when its waiter pod is lost with its node, and
only then: the retry re-attaches to the Slurm job, a failed job is final.
Argo marks a pod the kubelet terminated (Spot preemption, node pressure) Failed,
not Error, so OnError alone never retried it.
Run:  python -m pytest tests/ -v
"""

import re
import runpy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kubecore import enhance, meluxina  # noqa: E402

CONTEXT = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())

# Pod messages as the kubelet and Argo write them.
POD_LOST = [
    "Pod was terminated in response to imminent node shutdown.",
    "The node was low on resource: memory. Threshold quantity: 100Mi, available: 9Mi. ",
    "The node had condition: [DiskPressure]. ",
    "Pod was rejected: Node didn't have enough resource: cpu",
    "pod deleted",
]
STEP_FAILED = [
    "Error (exit code 1)",
    "OOMKilled (exit code 137)",
    "Pod was active on the node longer than the specified deadline",
]


def _twin():
    ns = runpy.run_path(str(ROOT / "pipeline.py"), run_name="__pipeline__")
    wf = enhance.enhance(yaml.safe_load(ns["p"].wt.to_yaml()), CONTEXT)
    return next(t for t in wf["spec"]["templates"] if t["name"] == "meluxina-run")


def _retried(status: str, message: str) -> bool:
    """POD_LOSS_RETRY as Argo evaluates it (Go regexp `matches` is a search
    anchored by the expression's own `.*`)."""
    return status == "Error" or re.search(".*(%s).*" % meluxina.POD_LOSS_MESSAGES,
                                          message) is not None


def test_twin_retries_always_under_the_pod_loss_expression():
    retry = _twin()["retryStrategy"]
    assert retry["retryPolicy"] == "Always"
    assert retry["expression"] == meluxina.POD_LOSS_RETRY
    assert retry["limit"] == "2"


def test_a_lost_waiter_pod_is_retried():
    for message in POD_LOST:
        assert _retried("Failed", message), message
    assert _retried("Error", "")


def test_a_failed_step_is_not_retried():
    for message in STEP_FAILED:
        assert not _retried("Failed", message), message


def test_a_queued_job_logs_why_slurm_holds_it():
    """The kaos e2e reads `pending reason: <Slurm state_reason>` from the twin's log to
    tell a queue wait from a spent allocation (AssocGrpGRESMinutes). The accounting
    record the loop polls has no live reason, so it is read from slurmctld (API)."""
    src = meluxina.MELUXINA_SUBMIT_CODE
    loop = src[src.index("pending_reason = None"):src.index("if any(x in TERMINAL for x in st)")]
    assert "get(API + '/job/' + str(jid))" in loop and "state_reason" in loop
    assert "print('pending reason:', reason, flush=True)" in loop
    assert "if reason != pending_reason:" in loop  # once per change, not every poll
