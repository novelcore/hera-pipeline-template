"""PRD-HPC-1461 (D-58/D-59/D-63, F-35): with pipeline-context hpc.controller "serve" the `meluxina-run`
template is the credential-free follower of the pool's HPC controller. Any other value, or none (the
controller does not serve the project), renders a template that only fails with a clear message: there
is no in-pod path to fall back to.
Run:  python -m pytest tests/ -v
"""
import copy
import json
import runpy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kubecore import enhance, meluxina  # noqa: E402

BASE = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())
IMAGE = "registry.example/kaos-hpc-operator:v1.2.3"
GOLDEN = ROOT / "tests" / "golden"


def _render(**hpc):
    ctx = copy.deepcopy(BASE)
    ctx["hpc"].update(hpc)
    ns = runpy.run_path(str(ROOT / "pipeline.py"), run_name="__pipeline__")
    return enhance.enhance(yaml.safe_load(ns["p"].wt.to_yaml()), ctx)


def _tpl(wf):
    return next(t for t in wf["spec"]["templates"] if t["name"] == "meluxina-run")


def _env(tpl):
    return {e["name"]: e for e in tpl["container"]["env"]}


@pytest.fixture(scope="module")
def serve():
    return _render(controller="serve", followerImage=IMAGE)


def test_serve_template_is_the_follower(serve):
    c = _tpl(serve)["container"]
    assert c["image"] == IMAGE
    assert c["command"] == ["/follower"]


def test_serve_env_is_the_follower_interface(serve):
    env = _env(_tpl(serve))
    assert env["HPC_JOB_NAMESPACE"] == {"name": "HPC_JOB_NAMESPACE",
                                        "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}}}
    want = {"WF_NAME": "{{workflow.name}}", "WF_UID": "{{workflow.uid}}",
            "STEP_NAME": "{{inputs.parameters.step-name}}",
            "NODE_KEY": "{{inputs.parameters.step-name}}-meluxina",
            "IMAGE_REF": "{{inputs.parameters.image}}", "STEP_COMMAND": "{{inputs.parameters.step-command}}",
            "SLURM_TIME_LIMIT": "{{inputs.parameters.time-limit}}", "HPC_CLASS": "{{inputs.parameters.hpc-class}}",
            "HPC_RESUMABLE_LEAD": "{{inputs.parameters.resumable-lead}}",
            "HPC_MAX_CONTINUATIONS": str(meluxina.HPC_MAX_CONTINUATIONS),
            "STEP_OUTPUTS": "{{inputs.parameters.step-outputs}}"}
    for k, v in want.items():
        assert env[k]["value"] == v, k
    for k in ("DATASET", "OUTPUTS_REPO", "OUTPUTS_REF", "CHECKPOINT_BUCKET", "CHECKPOINT_PREFIX"):
        assert k in env, k


def test_serve_env_is_only_the_allowlist_and_interface(serve):
    allowed = {"HPC_JOB_NAMESPACE", "WF_NAME", "WF_UID", "STEP_NAME", "NODE_KEY", "IMAGE_REF", "STEP_COMMAND",
               "SLURM_TIME_LIMIT", "HPC_CLASS", "HPC_RESUMABLE_LEAD", "HPC_MAX_CONTINUATIONS", "STEP_OUTPUTS",
               "DATASET", "HPC_SHARING", "HPC_SCOPE", "OUTPUTS_REPO", "OUTPUTS_REF", "CHECKPOINT_BUCKET",
               "CHECKPOINT_PREFIX", meluxina.KAOS_LIB_SUPPORT_ENV}
    assert set(_env(_tpl(serve))) <= allowed


def test_serve_has_no_secret_volume_env_or_endpoint(serve):
    tpl = _tpl(serve)
    assert "volumes" not in tpl and "volumeMounts" not in tpl["container"]
    text = json.dumps(tpl)
    for needle in ("secretKeyRef", '"secret"', "SLURM_TOKEN", "meluxina-jwt", "meluxina-staging", "mlflow-svc",
                   "ZITADEL", "MLFLOW_EXTERNAL_URL", "LAKEFS_EXTERNAL_URL", "HPC_ACCOUNT", "HPC_USER",
                   "HPC_SCRATCH", "HPC_HOME", "HPC_CLASSES_JSON", "HPC_CONTROLLER", "PLACEHOLDER-account", "PLACEHOLDER-user"):
        assert needle not in text, needle


def test_serve_keeps_inputs_outputs_deadline_retry_labels(serve):
    new = _tpl(serve)
    assert {p["name"] for p in new["inputs"]["parameters"]} == {
        "step-name", "image", "step-command", "time-limit", "deadline-seconds", "step-outputs", "hpc-class",
        "resumable-lead"}
    assert new["activeDeadlineSeconds"] == "{{inputs.parameters.deadline-seconds}}"
    assert new["retryStrategy"]["retryPolicy"] == "Always" and new["retryStrategy"]["limit"] == "2"
    assert new["retryStrategy"]["expression"] == meluxina.POD_LOSS_RETRY
    assert new["metadata"]["labels"]["platform.kubecore.io/compute-type"] == "hpc"
    assert {"slurm-job-id"} <= {p["name"] for p in new["outputs"]["parameters"]}


def test_serve_dag_is_unchanged_apart_from_the_template(serve):
    old = _render(controller=None)
    strip = lambda wf: [t for t in wf["spec"]["templates"] if t["name"] != "meluxina-run"]  # noqa: E731
    assert strip(serve) == strip(old)


def test_serve_without_follower_image_fails_the_render():
    for hpc in ({"controller": "serve", "followerImage": None}, {"controller": "serve", "followerImage": ""}):
        with pytest.raises(ValueError, match="followerImage"):
            _render(**hpc)


def test_serve_carries_sharing():
    env = _env(_tpl(_render(controller="serve", followerImage=IMAGE, sharing="on", scope="abcd1234")))
    assert env["HPC_SHARING"]["value"] == "on" and env["HPC_SCOPE"]["value"] == "abcd1234"


def test_node_key_is_unique_per_twin_and_stable_across_retries(serve):
    """NODE_KEY = step-name + provider = the twin's DAG task name: unique (Argo requires unique task names
    in a DAG; the enhancer emits one twin per routed task and copies no withItems/withParam), and a retry of
    the twin is a new pod of the same task with the same parameter (Argo's "(n)" retry suffix is on the node
    name, never in an input parameter)."""
    dag = next(t for t in serve["spec"]["templates"] if t["name"] == serve["spec"]["entrypoint"])
    twins = [t for t in dag["dag"]["tasks"] if t.get("template") == "meluxina-run"]
    assert twins
    keys = [next(p["value"] for p in t["arguments"]["parameters"] if p["name"] == "step-name") + "-meluxina"
            for t in twins]
    assert keys == [t["name"] for t in twins]
    assert len(set(keys)) == len(keys)
    assert not any(k in t for t in twins for k in ("withItems", "withParam", "withSequence"))


def test_serve_without_sharing_adds_no_sharing_env(serve):
    env = _env(_tpl(serve))
    assert "HPC_SHARING" not in env and "HPC_SCOPE" not in env
    assert meluxina.sharing_env({"hpc": {"sharing": "on"}}) == [], "no scope, no sharing"
    assert meluxina.sharing_env({"hpc": {"sharing": "off", "scope": "a1b2c3d4e5"}}) == []
    assert meluxina.sharing_env({"hpc": {"sharing": True, "scope": "a1b2c3d4e5"}})[0]["value"] == "on", \
        "a bare YAML on (read as True) still means on"


@pytest.mark.parametrize("controller", [None, "on", "off", "", "Serve", True])
def test_a_project_the_controller_does_not_serve_gets_a_refusal_never_the_waiter(controller):
    """F-35: absent, the retired phase-0 value "on" and anything else is a step that fails with the
    message; it holds no credential, no volume, no Slurm or staging code, and is not retried."""
    tpl = _tpl(_render(controller=controller))
    c = tpl["container"]
    assert c["command"] == ["sh", "-c"] and "exit 1" in c["args"][0]
    assert c["env"] == [{"name": "HPC_NOT_SERVED", "value": meluxina.HPC_NOT_SERVED_MESSAGE}]
    assert "enable operators.hpc on the pool" in meluxina.HPC_NOT_SERVED_MESSAGE
    assert "volumes" not in tpl and "volumeMounts" not in c
    assert "retryStrategy" not in tpl and "activeDeadlineSeconds" not in tpl
    text = json.dumps(tpl)
    for needle in ("secretKeyRef", "SLURM_TOKEN", "meluxina-jwt", "meluxina-staging", "mlflow-svc", "ZITADEL",
                   "HPC_CONTROLLER", "slurm-api.lxp.lu", "python3"):
        assert needle not in text, needle
    # the DAG still renders: a pipeline that never picks a MeluXina class is unaffected
    assert {p["name"] for p in tpl["inputs"]["parameters"]} >= {"step-name", "image", "hpc-class"}


def test_the_refusal_and_the_follower_share_the_dag(serve):
    refusal = _render(controller=None)
    strip = lambda wf: [t for t in wf["spec"]["templates"] if t["name"] != "meluxina-run"]  # noqa: E731
    assert strip(serve) == strip(refusal)
