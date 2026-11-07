"""PRD-HPC-1461 D-76 — the Kubernetes backend of the one resilience contract (platform-owned).

`enhance_resilience` runs once per developer step and injects, with no client code:

  Tier 1  retryStrategy   a step lost with its node (spot preemption, eviction, node shutdown, deleted
                          pod) is re-run, at most twice, with backoff. NEVER on the step's own non-zero
                          exit (same expression as the HPC follower, `meluxina.POD_LOSS_RETRY`).
                          Safe because step outputs are published only on success.
  Folder  KAOS_CHECKPOINT_DIR   every step gets the env var and a pod-local emptyDir behind it.
  Tier 2  persistence     for GPU steps (and any step that sets `checkpoint_every`): an init container
                          restores the newest verified copy of the folder from lakeFS, a sidecar copies it
                          periodically and on SIGTERM. The code is `kubecore/checkpoint_helper.py`.

The helper image comes from the platform registry only (`checkpoints.helperImage`, see helper_image).

Opt-out per step: annotation `platform.kubecore.io/checkpoint-every: "off"` (authoring:
`checkpoint_every=False`) removes the persistence helper only; the re-run and the folder stay.

Where copies live: the app's lakeFS outputs repository `outputs-<app>` (see outputs_repo.py), on branch
`kaos-checkpoints` (never committed or merged), under `resume/<workflow name>/<step>/`.

Fill-absent like every pass of the enhancer: a developer-set retryStrategy, env var, volume or sidecar of
the same name is left alone.
"""
import base64
import re
import sys
import zlib
from pathlib import Path

from kubecore.meluxina import POD_LOSS_RETRY
from kubecore.outputs_repo import outputs_repo

CHECKPOINT_ENV = "KAOS_CHECKPOINT_DIR"
CHECKPOINT_MOUNT = "/kaos/checkpoint"
CHECKPOINT_VOLUME = "kaos-checkpoint"
STAGE_VOLUME = "kaos-checkpoint-stage"
STAGE_MOUNT = "/stage"
CHECKPOINT_BRANCH = "kaos-checkpoints"
CHECKPOINT_ROOT = "resume"
DEFAULT_EVERY_MINUTES = 10
RETRY_LIMIT = "2"
RETRY_BACKOFF = {"duration": "30s", "factor": "2", "maxDuration": "10m"}
INIT_NAME = "kaos-ckpt-restore"
SIDECAR_NAME = "kaos-ckpt-copy"
HELPER_PATH = Path(__file__).with_name("checkpoint_helper.py")
EVERY_RE = re.compile(r"^(off|[0-9]+)$")


def retry_strategy() -> dict:
    """Tier 1: retry only a step lost with its node, never one that failed by itself."""
    return {"limit": RETRY_LIMIT, "retryPolicy": "Always", "expression": POD_LOSS_RETRY,
            "backoff": dict(RETRY_BACKOFF)}


def helper_image(ctx: dict) -> str:
    """The image the helper containers run, from the platform registry: `checkpoints.helperImage`, which the
    operator publishes in every app's pipeline context (the pool's pinned kaos-hpc-operator image), else the
    HPC follower image (the same image). Empty when the context has neither: there is deliberately NO public
    registry fallback (no third-party pull in tenant pods); the step then gets the re-run and the folder
    but no copies, and the app picks the image up on its next render."""
    named = (ctx.get("checkpoints") or {}).get("helperImage")
    follower = (ctx.get("hpc") or {}).get("followerImage")
    return str(named or follower or "")


def helper_boot() -> str:
    """`python3 -c` program that runs the embedded helper: argv[1] is `restore` or `watch`."""
    blob = base64.b64encode(zlib.compress(HELPER_PATH.read_bytes(), 9)).decode()
    return ("import base64,zlib;exec(zlib.decompress(base64.b64decode('%s')).decode(),"
            "{'__name__':'__main__'})" % blob)


def every_minutes(annots: dict) -> str:
    """The step's copy interval: 'off', minutes as text, or '' for the default."""
    raw = (annots.get("checkpoint-every") or "").strip().lower()
    if raw and not EVERY_RE.match(raw):
        raise ValueError("platform.kubecore.io/checkpoint-every=%r: expected 'off' or minutes like '20'" % raw)
    return raw


def shared_templates(spec: dict) -> set:
    """Templates run by more than one DAG task or by a fan-out: one checkpoint key would be shared."""
    uses, fanned = {}, set()
    for tpl in spec.get("templates", []):
        for task in (tpl.get("dag") or {}).get("tasks", []):
            name = task.get("template")
            uses[name] = uses.get(name, 0) + 1
            if any(k in task for k in ("withItems", "withParam", "withSequence")):
                fanned.add(name)
    return fanned | {n for n, c in uses.items() if c > 1}


def wants_helper(step: dict, gpu: bool, every: str, ctx: dict, inject_off: bool, shared: set) -> bool:
    if every == "off" or inject_off or step["name"] in shared:
        return False
    lakefs = ctx.get("lakefs") or {}
    if not (lakefs.get("endpoint") and lakefs.get("adminSecret") and lakefs.get("adminSecretKeys")):
        return False
    if not (gpu or every):
        return False
    if not helper_image(ctx):
        print("kubecore: step %r: no checkpoints.helperImage in the pipeline context; its checkpoint copies are "
              "off until the platform publishes it (re-run and folder are still injected)" % step["name"],
              file=sys.stderr)
        return False
    return True    # CPU steps opt in with a checkpoint_every value


def _add_named(items: list, entry: dict) -> None:
    if not any(i.get("name") == entry["name"] for i in items):
        items.append(entry)


def helper_env(step: dict, ctx: dict, every: str) -> list:
    keys, secret = ctx["lakefs"]["adminSecretKeys"], ctx["lakefs"]["adminSecret"]
    ref = lambda key: {"secretKeyRef": {"name": secret, "key": keys[key]}}  # noqa: E731
    return [
        {"name": CHECKPOINT_ENV, "value": CHECKPOINT_MOUNT},
        {"name": "LAKEFS_ENDPOINT", "value": ctx["lakefs"]["endpoint"]},
        {"name": "LAKEFS_ACCESS_KEY", "valueFrom": ref("accessKey")},
        {"name": "LAKEFS_SECRET_KEY", "valueFrom": ref("secretKey")},
        {"name": "CKPT_REPO", "value": outputs_repo(ctx)},
        {"name": "CKPT_BRANCH", "value": CHECKPOINT_BRANCH},
        {"name": "CKPT_ROOT", "value": CHECKPOINT_ROOT},
        {"name": "CKPT_KEY", "value": "{{workflow.name}}/%s" % step["name"]},
        {"name": "CKPT_EVERY_MIN", "value": every if every.isdigit() else str(DEFAULT_EVERY_MINUTES)},
        {"name": "CKPT_STAGE", "value": STAGE_MOUNT},
        {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
    ]


def helper_container(name: str, mode: str, step: dict, ctx: dict, every: str) -> dict:
    """One helper container (init or sidecar): small requests, locked down, never the step's GPU."""
    return {
        "name": name, "image": helper_image(ctx),
        "command": ["python3", "-c", helper_boot(), mode],
        "env": helper_env(step, ctx, every),
        "resources": {"requests": {"cpu": "10m", "memory": "64Mi"}, "limits": {"memory": "512Mi"}},
        "securityContext": {"runAsUser": 65532, "runAsGroup": 65532, "allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
        "volumeMounts": [{"name": CHECKPOINT_VOLUME, "mountPath": CHECKPOINT_MOUNT},
                         {"name": STAGE_VOLUME, "mountPath": STAGE_MOUNT}],
    }


def inject_folder(step: dict, helper: bool) -> bool:
    """Env var + emptyDir for the folder. Returns False when the developer chose their own folder."""
    container = step["container"]
    env = container.setdefault("env", [])
    if any(e.get("name") == CHECKPOINT_ENV for e in env):
        return False
    env.append({"name": CHECKPOINT_ENV, "value": CHECKPOINT_MOUNT})
    mounts = container.setdefault("volumeMounts", [])
    if not any(m.get("mountPath") == CHECKPOINT_MOUNT for m in mounts):
        mounts.append({"name": CHECKPOINT_VOLUME, "mountPath": CHECKPOINT_MOUNT})
    _add_named(step.setdefault("volumes", []), {"name": CHECKPOINT_VOLUME, "emptyDir": {}})
    if helper:
        _add_named(step["volumes"], {"name": STAGE_VOLUME, "emptyDir": {}})
    return True


def enhance_resilience(spec: dict, step: dict, ctx: dict, annots: dict, gpu: bool, inject_off: bool,
                       shared: set) -> None:
    """Apply the Kubernetes backend of the resilience contract to one step template."""
    step.setdefault("retryStrategy", retry_strategy())
    every = every_minutes(annots)
    helper = wants_helper(step, gpu, every, ctx, inject_off, shared)
    if not inject_folder(step, helper) or not helper:
        return
    step.setdefault("initContainers", [])
    step.setdefault("sidecars", [])
    _add_named(step["initContainers"], helper_container(INIT_NAME, "restore", step, ctx, every))
    _add_named(step["sidecars"], helper_container(SIDECAR_NAME, "watch", step, ctx, every))
