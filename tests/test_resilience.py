"""The Kubernetes backend of the resilience contract (PRD-HPC-1461 D-76), as the enhancer renders it.

Tier 1 re-run (retryStrategy), the KAOS_CHECKPOINT_DIR folder on every step, and the restore init
container + copy sidecar on GPU steps (or any step with checkpoint_every). The GPU step's injected pieces
are compared with tests/golden/resilience_gpu_step.yaml (regenerate: UPDATE_GOLDEN=1 pytest).
Run:  python -m pytest tests/ -v
"""
import base64
import copy
import os
import re
import sys
import zlib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kubecore import authoring, enhance, meluxina, resilience  # noqa: E402

CONTEXT = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())
CONTEXT.pop("hpc")      # in-cluster only: no MeluXina twins in these renders
GOLDEN = ROOT / "tests" / "golden" / "resilience_gpu_step.yaml"
INJECTED = ("retryStrategy", "volumes", "initContainers", "sidecars")


def render(build, ctx=None):
    with authoring.pipeline("t") as p:
        build()
    wf = enhance.enhance(yaml.safe_load(p.wt.to_yaml()), ctx or CONTEXT)
    return {t["name"]: t for t in wf["spec"]["templates"]}


def env_of(tpl, container="container"):
    return {e["name"]: e for e in tpl[container]["env"]}


def pipeline_steps():
    authoring.step("prep")
    authoring.step("train", gpu=True)
    authoring.step("cpu-opt-in", checkpoint_every="20m")
    authoring.step("gpu-off", gpu=True, checkpoint_every=False)


@pytest.fixture(scope="module")
def tpls():
    return render(pipeline_steps)


def test_should_retry_every_step_only_when_the_node_is_lost(tpls):
    for name in ("prep", "train", "cpu-opt-in", "gpu-off", "compose-and-validate"):
        retry = tpls[name]["retryStrategy"]
        assert retry["retryPolicy"] == "Always" and retry["limit"] == "2"
        assert retry["expression"] == meluxina.POD_LOSS_RETRY      # one expression for both backends
        assert retry["backoff"]["duration"] == "30s"


def test_should_not_retry_the_steps_own_failure(tpls):
    msgs = meluxina.POD_LOSS_MESSAGES
    for own in ("Error (exit code 1)", "OOMKilled (exit code 137)", "Error (exit code 85)"):
        assert not re.search(".*(%s).*" % msgs, own), own


def test_should_keep_a_retry_strategy_the_developer_set():
    def build():
        authoring.step("s")
    with authoring.pipeline("t") as p:
        build()
    raw = yaml.safe_load(p.wt.to_yaml())
    next(t for t in raw["spec"]["templates"] if t["name"] == "s")["retryStrategy"] = {"limit": "5"}
    wf = enhance.enhance(raw, CONTEXT)
    assert next(t for t in wf["spec"]["templates"] if t["name"] == "s")["retryStrategy"] == {"limit": "5"}


def test_should_give_every_step_the_folder_env_and_an_empty_dir(tpls):
    for name in ("prep", "train", "cpu-opt-in", "gpu-off"):
        tpl = tpls[name]
        assert env_of(tpl)["KAOS_CHECKPOINT_DIR"]["value"] == resilience.CHECKPOINT_MOUNT
        assert {"name": "kaos-checkpoint", "emptyDir": {}} in tpl["volumes"]
        assert {"name": "kaos-checkpoint", "mountPath": "/kaos/checkpoint"} in tpl["container"]["volumeMounts"]


def test_should_add_the_helper_to_gpu_steps_and_opt_in_cpu_steps_only(tpls):
    assert [c["name"] for c in tpls["train"]["initContainers"]] == ["kaos-ckpt-restore"]
    assert [c["name"] for c in tpls["train"]["sidecars"]] == ["kaos-ckpt-copy"]
    assert "sidecars" in tpls["cpu-opt-in"]
    for name in ("prep", "gpu-off", "compose-and-validate"):
        assert "sidecars" not in tpls[name] and "initContainers" not in tpls[name]


def test_should_use_the_interval_the_step_asked_for(tpls):
    side = {e["name"]: e for e in tpls["cpu-opt-in"]["sidecars"][0]["env"]}
    assert side["CKPT_EVERY_MIN"]["value"] == "20"
    assert {e["name"]: e for e in tpls["train"]["sidecars"][0]["env"]}["CKPT_EVERY_MIN"]["value"] == "10"


def test_should_key_the_copies_by_workflow_and_step_in_the_outputs_repository(tpls):
    env = {e["name"]: e for e in tpls["train"]["sidecars"][0]["env"]}
    assert env["CKPT_KEY"]["value"] == "{{workflow.name}}/train"
    assert env["CKPT_REPO"]["value"] == "outputs-PLACEHOLDER-app"
    assert env["CKPT_BRANCH"]["value"] == "kaos-checkpoints"
    assert env["LAKEFS_ACCESS_KEY"]["valueFrom"]["secretKeyRef"]["name"] == "PLACEHOLDER-lakefs-admin"


def test_should_lock_down_the_helper_and_give_it_small_requests(tpls):
    for c in tpls["train"]["initContainers"] + tpls["train"]["sidecars"]:
        assert c["securityContext"]["readOnlyRootFilesystem"] is True
        assert c["securityContext"]["capabilities"] == {"drop": ["ALL"]}
        assert "nvidia.com/gpu" not in str(c["resources"])
        assert c["resources"]["requests"] == {"cpu": "10m", "memory": "64Mi"}


def test_should_embed_exactly_the_helper_source_without_argo_markers():
    boot = resilience.helper_boot()
    blob = re.search(r"b64decode\('([^']+)'\)", boot).group(1)
    source = zlib.decompress(base64.b64decode(blob))
    assert source == resilience.HELPER_PATH.read_bytes()
    assert "{{" not in boot and "{{" not in source.decode()


def test_should_prefer_a_platform_image_over_the_default():
    assert resilience.helper_image({}) == resilience.DEFAULT_HELPER_IMAGE
    ctx = {"hpc": {"enabled": True, "controller": "serve", "followerImage": "reg/kaos-hpc-operator:v1"}}
    assert resilience.helper_image(ctx) == "reg/kaos-hpc-operator:v1"
    ctx["checkpoints"] = {"helperImage": "reg/helper:v2"}
    assert resilience.helper_image(ctx) == "reg/helper:v2"


def test_should_skip_the_helper_for_fan_out_and_shared_templates():
    def build():
        authoring.step("a", gpu=True)
    with authoring.pipeline("t") as p:
        build()
    raw = yaml.safe_load(p.wt.to_yaml())
    main = next(t for t in raw["spec"]["templates"] if t["name"] == "main")
    task = next(t for t in main["dag"]["tasks"] if t["name"] == "a")
    task["withItems"] = [1, 2]
    wf = enhance.enhance(raw, CONTEXT)
    a = next(t for t in wf["spec"]["templates"] if t["name"] == "a")
    assert "sidecars" not in a and "retryStrategy" in a and "KAOS_CHECKPOINT_DIR" in env_of(a)


def test_should_skip_the_helper_when_lakefs_injection_is_off():
    def build():
        authoring.step("a", gpu=True)
    with authoring.pipeline("t") as p:
        build()
    raw = yaml.safe_load(p.wt.to_yaml())
    tpl = next(t for t in raw["spec"]["templates"] if t["name"] == "a")
    tpl.setdefault("metadata", {}).setdefault("annotations", {})["platform.kubecore.io/inject"] = "lakefs=false"
    a = next(t for t in enhance.enhance(raw, CONTEXT)["spec"]["templates"] if t["name"] == "a")
    assert "sidecars" not in a


def test_should_keep_the_developers_own_checkpoint_folder():
    with authoring.pipeline("t") as p:
        authoring.step("a", gpu=True)
    raw = yaml.safe_load(p.wt.to_yaml())
    tpl = next(t for t in raw["spec"]["templates"] if t["name"] == "a")
    tpl["container"]["env"] = [{"name": "KAOS_CHECKPOINT_DIR", "value": "/mine"}]
    a = next(t for t in enhance.enhance(raw, CONTEXT)["spec"]["templates"] if t["name"] == "a")
    assert env_of(a)["KAOS_CHECKPOINT_DIR"]["value"] == "/mine" and "sidecars" not in a


@pytest.mark.parametrize("bad", ["soon", 0, "0m", True, "10 min"])
def test_should_reject_a_bad_checkpoint_every(bad):
    with pytest.raises(authoring.AuthoringError):
        with authoring.pipeline("t"):
            authoring.step("a", gpu=True, checkpoint_every=bad)


@pytest.mark.parametrize("given,annotation", [("20m", "20"), ("1h", "60"), (30, "30"), (False, "off")])
def test_should_map_checkpoint_every_to_the_annotation(given, annotation):
    with authoring.pipeline("t") as p:
        authoring.step("a", checkpoint_every=given)
    tpl = next(t for t in yaml.safe_load(p.wt.to_yaml())["spec"]["templates"] if t["name"] == "a")
    assert tpl["metadata"]["annotations"]["platform.kubecore.io/checkpoint-every"] == annotation


def test_should_not_change_the_hpc_follower_template():
    ctx = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())
    tpls = render(pipeline_steps, ctx)
    follower = tpls["meluxina-run"]
    assert follower["retryStrategy"]["limit"] == "2" and "sidecars" not in follower
    assert "KAOS_CHECKPOINT_DIR" not in str(follower["container"]["env"])


def test_should_render_the_gpu_step_like_the_golden_file(tpls):
    got = {k: copy.deepcopy(tpls["train"][k]) for k in INJECTED}
    for c in got["initContainers"] + got["sidecars"]:
        c["command"][2] = "<helper source, compressed: see kubecore/checkpoint_helper.py>"
    got["checkpointEnv"] = [e for e in tpls["train"]["container"]["env"] if e["name"] == "KAOS_CHECKPOINT_DIR"]
    got["checkpointMount"] = [m for m in tpls["train"]["container"]["volumeMounts"] if m["name"] == "kaos-checkpoint"]
    text = yaml.safe_dump(got, sort_keys=False)
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(text)
    assert text == GOLDEN.read_text()
