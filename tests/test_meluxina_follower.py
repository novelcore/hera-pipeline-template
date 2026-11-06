"""PRD-HPC-1461 phase 1 (D-58/D-59/D-63): with pipeline-context hpc.controller "serve" the `meluxina-run`
template is the credential-free follower of the pool's HPC controller. "on" (phase 0) and an absent switch
render the in-pod waiter exactly as before (goldens in tests/golden, taken from dev be9e52b).
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
    old, new = _tpl(_render()), _tpl(serve)
    for k in ("inputs", "outputs", "activeDeadlineSeconds", "retryStrategy", "metadata"):
        assert new[k] == old[k], k
    assert {"slurm-job-id"} <= {p["name"] for p in new["outputs"]["parameters"]}


def test_serve_dag_is_unchanged_apart_from_the_template(serve):
    old = _render()
    strip = lambda wf: [t for t in wf["spec"]["templates"] if t["name"] != "meluxina-run"]  # noqa: E731
    assert strip(serve) == strip(old)


def test_serve_without_follower_image_fails_the_render():
    for hpc in ({"controller": "serve"}, {"controller": "serve", "followerImage": ""}):
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


@pytest.mark.parametrize("name,hpc", [("absent", {}), ("on", {"controller": "on"})])
def test_on_and_absent_render_the_waiter_unchanged(name, hpc):
    golden = json.loads((GOLDEN / ("meluxina-run-%s.json" % name)).read_text())
    assert json.loads(json.dumps(_tpl(_render(**hpc)))) == golden


def test_other_controller_values_stay_the_waiter():
    for v in ("off", "", None, "Serve"):
        assert _tpl(_render(controller=v)) == _tpl(_render())
