"""PRD-HPC-1461 F-26 / D-34, phase 0 "observe and admit" (AC-40): with the pool's HPC controller on, the
runner records every attempt of its step as an HPCArgoWorkflowJob, submits only after the controller
admitted and booked it, and reports the site job so the controller settles each attempt and decides a
continuation. Off, nothing changes. On but unusable, the step fails rather than submit around it.

The runner's own functions run against a fake Kubernetes API.
Run:  python -m pytest tests/ -v
"""
import ast
import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kubecore.meluxina import MELUXINA_SUBMIT_CODE as SRC  # noqa: E402

FUNCS = ("record_name", "record_path", "record_spec", "record_unusable", "ensure_record", "await_admission",
         "site_time", "report", "checkpoint_uri", "resume_of")


class FakeAPI:
    """The calls the runner makes: create/get its record, merge-patch its status."""

    def __init__(self):
        self.record = None
        self.calls = []
        self.fail = []          # HTTP codes (or Exception instances) to answer the next calls with
        self.statuses = []      # status dicts the next GETs return, in order (the last one repeats)

    def __call__(self, method, path, body=None, ctype="application/json"):
        self.calls.append((method, path, body, ctype))
        if self.fail:
            f = self.fail.pop(0)
            if isinstance(f, Exception):
                raise f
            raise urllib.error.HTTPError(path, f, "x", {}, io.BytesIO(b"{}"))
        if method == "POST":
            if self.record is not None:
                raise urllib.error.HTTPError(path, 409, "exists", {}, io.BytesIO(b"{}"))
            self.record = dict(body, status={})
            return self.record
        if method == "GET":
            if self.statuses:
                self.record["status"] = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return self.record
        if method == "PATCH":
            run = body["status"]["run"]
            self.record.setdefault("status", {})["run"] = {k: v for k, v in run.items() if v is not None}
            return self.record
        raise AssertionError(method)


@pytest.fixture
def runner(monkeypatch, tmp_path):
    sa = tmp_path / "sa"
    sa.mkdir()
    (sa / "namespace").write_text("proj-a-ml-dev\n")
    env = {"STEP_NAME": "model-training", "KUBECORE_WORKFLOW_NAME": "yolo-pipeline-x7k2p",
           "WF_UID": "0b7f6c1e-1111-2222-3333-444455556666", "HPC_CLASS": "meluxina-gpu",
           "STEP_COMMAND": json.dumps(["python", "-m", "train", "--epochs", "3"]), "SLURM_TIME_LIMIT": "720",
           "STEP_OUTPUTS": "training-result", "DATASET": "dataset-default@latest", "OUTPUTS_REPO": "outputs-yolo"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    tree = ast.parse(SRC)
    src = "\n\n".join(ast.get_source_segment(SRC, n) for n in tree.body
                      if isinstance(n, ast.FunctionDef) and n.name in FUNCS)
    api = FakeAPI()
    out = []
    g = {"os": os, "re": re, "json": json, "sys": sys, "hashlib": hashlib, "urllib": urllib,
         "time": type("T", (), {"sleep": staticmethod(lambda s: None), "strftime": __import__("time").strftime,
                               "gmtime": __import__("time").gmtime}),
         "k8s": api, "K8S_SA": str(sa), "img": "zot.example/proj/yolo@sha256:" + "a" * 64,
         "RESUMABLE_LEAD_MIN": 0, "MAX_CONTINUATIONS": 5, "ATTEMPT": 1, "CONTROLLER": True,
         "dataset_coords": lambda: ("dataset-default", "latest"),
         "print": lambda *a, **k: out.append(" ".join(str(x) for x in a))}
    for k in ("RECORD_ACTIVE", "RECORD_TERMINAL", "RUN_FIELDS"):
        node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == k)
        exec(ast.get_source_segment(SRC, node), g)
    exec(src, g)
    g["api"], g["out"] = api, out
    return g


def test_one_record_per_step_of_a_run_with_a_valid_name(runner):
    assert runner["record_name"]() == "yolo-pipeline-x7k2p-model-training"
    assert runner["record_path"]() == ("/apis/hpc.kaos.io/v1alpha1/namespaces/proj-a-ml-dev/"
                                       "hpcargoworkflowjobs/yolo-pipeline-x7k2p-model-training")
    os.environ["KUBECORE_WORKFLOW_NAME"] = "A_Very_Long_Workflow_Name_" * 4
    name = runner["record_name"]()
    assert len(name) <= 63 and re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", name)
    assert name == runner["record_name"](), "deterministic: a retried waiter finds the same record"


def test_the_spec_describes_the_step_and_never_a_project_or_site(runner):
    spec = runner["record_spec"]()
    assert spec == {"class": "meluxina-gpu", "image": runner["img"],
                    "command": ["python", "-m", "train", "--epochs", "3"], "wallTimeMinutes": 720, "nodes": 1,
                    "outputs": ["training-result"], "datasetRef": "dataset-default@latest"}
    runner["RESUMABLE_LEAD_MIN"] = 20
    assert runner["record_spec"]()["resumable"] == {"leadMinutes": 20, "maxContinuations": 5}


def test_the_record_is_created_owned_by_the_workflow(runner):
    rec = runner["ensure_record"]()
    method, path, body, _ = runner["api"].calls[0]
    assert method == "POST" and path.endswith("/hpcargoworkflowjobs")
    assert body["metadata"]["ownerReferences"] == [{"apiVersion": "argoproj.io/v1alpha1", "kind": "Workflow",
                                                    "name": "yolo-pipeline-x7k2p",
                                                    "uid": "0b7f6c1e-1111-2222-3333-444455556666"}]
    assert rec["metadata"]["name"] == "yolo-pipeline-x7k2p-model-training"


def test_a_retried_waiter_reads_the_existing_record(runner):
    runner["api"].record = {"metadata": {"name": "x"}, "status": {"attempt": 3, "continuations": 2}}
    assert runner["ensure_record"]()["status"]["attempt"] == 3
    assert [c[0] for c in runner["api"].calls] == ["POST", "GET"]


def test_a_transient_api_error_is_retried(runner):
    runner["api"].fail = [500, OSError("connection reset")]
    assert runner["ensure_record"]()["metadata"]["name"] == "yolo-pipeline-x7k2p-model-training"


@pytest.mark.parametrize("code, why", [(404, "no HPC controller"), (403, "may not create")])
def test_without_a_usable_controller_the_step_never_submits_around_it(runner, code, why):
    runner["api"].fail = [code]
    with pytest.raises(SystemExit) as e:
        runner["ensure_record"]()
    assert e.value.code == 1 and why in runner["out"][-1] and "not submitting around" in runner["out"][-1]


def test_submission_waits_for_admission(runner):
    runner["ensure_record"]()
    runner["api"].statuses = [{}, {"phase": "Waiting", "reason": "WaitingForBudget"},
                              {"phase": "Waiting", "reason": "WaitingForBudget"},
                              {"phase": "Admitted", "attempt": 1, "booking": {"nodeMinutes": 720, "siteName": "meluxina"}}]
    st = runner["await_admission"](1)
    assert st["phase"] == "Admitted"
    printed = runner["out"]
    assert sum("WaitingForBudget" in p for p in printed) == 1, "a reason is printed when it changes"
    assert "720 node-minutes booked on meluxina" in printed[-1]


def test_a_continuation_waits_until_the_controller_admits_the_next_attempt(runner):
    runner["ensure_record"]()
    runner["api"].statuses = [{"phase": "Running", "attempt": 1},                     # not settled yet
                              {"phase": "Pending", "attempt": 2, "reason": "Continuing"},
                              {"phase": "Admitted", "attempt": 2, "booking": {}}]
    assert runner["await_admission"](2)["attempt"] == 2


@pytest.mark.parametrize("status", [{"phase": "Refused", "reason": "BudgetBlocked"},
                                    {"phase": "Failed", "reason": "ContinuationLimit"},
                                    {"phase": "Cancelled"}])
def test_a_refusal_or_an_ended_record_ends_the_step_with_its_reason(runner, status):
    runner["ensure_record"]()
    runner["api"].statuses = [status]
    with pytest.raises(SystemExit) as e:
        runner["await_admission"](1)
    assert e.value.code == 1 and status["phase"] in runner["out"][-1]


def test_every_report_writes_the_whole_run_so_nothing_of_an_earlier_attempt_survives(runner):
    runner["ensure_record"]()
    runner["ATTEMPT"] = 1
    runner["report"](siteJobID="5425070", state="FAILED", exitCode=85, terminal=True,
                     checkpointRef="lakefs://outputs-yolo/" + "ab" * 32 + "/hpc-checkpoints/w/s/attempt-1/")
    runner["ATTEMPT"] = 2
    runner["report"](siteJobID="5425099", state="PENDING")
    _, path, body, ctype = runner["api"].calls[-1]
    assert path.endswith("/status") and ctype == "application/merge-patch+json"
    assert set(body["status"]["run"]) == set(runner["RUN_FIELDS"])
    assert runner["api"].record["status"]["run"] == {"attempt": 2, "siteJobID": "5425099", "state": "PENDING"}


def test_the_end_of_an_attempt_is_reported_until_it_lands(runner):
    runner["ensure_record"]()
    runner["api"].fail = [500, 503, OSError("timeout")]
    runner["report"](must=True, siteJobID="1", state="COMPLETED", exitCode=0, terminal=True)
    assert runner["api"].record["status"]["run"]["terminal"] is True


def test_an_end_that_cannot_be_reported_fails_the_step(runner):
    runner["ensure_record"]()
    runner["api"].fail = [500] * 60
    with pytest.raises(SystemExit):
        runner["report"](must=True, siteJobID="1", state="COMPLETED", terminal=True)


def test_a_state_report_that_fails_does_not_stop_the_step(runner):
    runner["ensure_record"]()
    runner["api"].fail = [500]
    runner["report"](siteJobID="1", state="RUNNING")          # no exception


def test_with_the_controller_off_nothing_is_reported(runner):
    runner["CONTROLLER"] = False
    runner["report"](must=True, siteJobID="1", state="COMPLETED", terminal=True)
    assert runner["api"].calls == []


def test_the_checkpoint_ref_round_trips(runner):
    ckpt = ("ab" * 32, "hpc-checkpoints/wf/model-training/attempt-2/")
    assert runner["resume_of"](runner["checkpoint_uri"](ckpt)) == ckpt
    for bad in (None, "", "lakefs://r/not-a-commit/p/", "s3://x/" + "ab" * 32 + "/p/"):
        assert runner["resume_of"](bad) is None


def test_site_times_are_utc(runner):
    assert runner["site_time"]({"time": {"start": {"set": True, "number": 1762300800}}}, "start") \
        == "2025-11-05T00:00:00Z"
    assert runner["site_time"]({"time": {"end": 0}}, "end") is None


# ---------------------------------------------------------------- where the waiter calls them

def _main():
    return SRC[SRC.index("START_CONTINUATIONS = 0"):]


def test_a_new_attempt_is_submitted_only_after_admission_and_an_adopted_job_is_not_resubmitted():
    start = _main()[:_main().index("open('/tmp/slurm-job-id', 'w')")]
    assert start.index("ensure_record()") < start.index("find_active()") < start.index("await_admission(ATTEMPT)") \
        < start.index("jid = submit()")
    assert "if jid is not None:" in start   # an adopted (already admitted) job is followed, not resubmitted
    for k in ("ATTEMPT = max(int(st.get('attempt') or 1), 1)", "START_CONTINUATIONS = int(st.get('continuations') or 0)",
              "RESUME = resume_of((st.get('resume') or {}).get('checkpointRef'))"):
        assert k in start


def test_a_resubmit_keeps_the_attempt_and_only_replaces_the_site_job():
    sub = SRC[SRC.index("def submit():"):SRC.index("def submit_refusal(e):")]
    assert "report(siteJobID=str(j), state='PENDING')" in sub and "terminal" not in sub.split("report(")[1]


def test_a_continuation_reports_the_end_then_is_admitted_again_before_it_is_submitted():
    loop = _main()[_main().index("if rc == CHECKPOINT_EXIT"):]
    cont = loop[loop.index("why = ''"):loop.index("if 'COMPLETED' in st:")]
    order = [cont.index(s) for s in ("checkpointRef=checkpoint_uri(ckpt))", "ATTEMPT += 1",
                                     "await_admission(ATTEMPT)", "jid = submit()")]
    assert order == sorted(order)
    assert "report(must=True" in loop[:loop.index("why = ''") + 2000].split("if why:")[1].split("sys.exit(1)")[0]


def test_every_end_of_the_step_is_reported():
    tail = _main()[_main().index("if 'COMPLETED' in st:"):]
    assert tail.index("report(must=True") < tail.index("sys.exit(0 if")
    term = SRC[SRC.index("def on_term("):SRC.index("signal.signal(signal.SIGTERM, on_term)")]
    assert term.index("cancel(jid)") < term.index("state='CANCELLED', terminal=True")


def test_the_operator_switch_reaches_the_waiter():
    from kubecore import enhance, meluxina
    ctx = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())
    assert meluxina.controller_env(ctx) == []
    ctx["hpc"]["controller"] = "on"
    assert meluxina.controller_env(ctx) == [{"name": "HPC_CONTROLLER", "value": "on"}]
    import runpy
    ns = runpy.run_path(str(ROOT / "pipeline.py"), run_name="__pipeline__")
    wft = enhance.enhance(yaml.safe_load(ns["p"].wt.to_yaml()), ctx)
    (twin,) = [t for t in wft["spec"]["templates"] if t["name"] == "meluxina-run"]
    assert {"name": "HPC_CONTROLLER", "value": "on"} in twin["container"]["env"]
