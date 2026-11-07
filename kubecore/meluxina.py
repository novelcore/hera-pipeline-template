"""PRD-1016 — the MeluXina HPC leg the `platform.kubecore.io/hpc` annotation reserved.

`enhance_hpc` runs as the last enhancement pass. Active only when the pipeline
context carries `hpc.enabled` (Derive idiom: the operator sets it iff the
parent KubePool is HPC-ready, so non-HPC pools render byte-identically).

What it does (F-02/F-03/F-06):
  * re-emits the `target` submit-form parameter (gcp | <provider>);
  * every GPU step WITHOUT an existing task `when` (quantization-gated steps
    keep in-cluster-only behaviour this slice) gains a `-meluxina` twin DAG
    task with complementary `when:` clauses on `target`;
  * downstream `depends` tokens that reference a routed step are rewritten to
    gate on the Succeeded||Skipped twin pair (exactly one twin runs);
  * one `meluxina-run` CONTAINER template is appended (the release gate
    rejects script templates).

MeluXina runs only through the pool's HPC controller (PRD-HPC-1461 D-58, D-59,
F-35). The operator publishes pipeline-context hpc.controller "serve" (and
hpc.followerImage) when the controller serves the project; `meluxina-run` is
then a credential-free follower (see follower_template): it creates the step's
HPCArgoWorkflowJob, prints its progress and writes the Argo outputs from its
status. The controller's runner Job owns submission, staging, the Slurm token,
continuation and resubmits. The in-pod waiter this module used to embed is
gone: for a project the controller does not serve, `meluxina-run` is a step
that fails at once with HPC_NOT_SERVED_MESSAGE (see refusal_template) and
nothing is submitted.
"""
import json
import re

from kubecore.kaos_lib_support import ENV as KAOS_LIB_SUPPORT_ENV
from kubecore.kaos_lib_support import support_value
from kubecore.outputs_repo import OUTPUTS_REF, checkpoint_prefix, outputs_repo


_SUBST_TAG = re.compile(
    r"\{\{\s*((?:workflow\.parameters|tasks)\.[A-Za-z0-9_.-]+)\s*\}\}")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _tag_expr(path: str) -> str:
    """Convert a dotted Argo tag path to expression syntax, using bracket
    access for segments that are not bare identifiers (task and param names
    routinely carry hyphens: tasks.compose-and-validate.outputs...)."""
    segs = path.split(".")
    out = segs[0]
    for s in segs[1:]:
        out += "." + s if _IDENT.match(s) else "['%s']" % s
    return out


_TASK_OUTPUT = re.compile(r"^tasks\.([A-Za-z0-9_-]+)\.outputs\.parameters\.([A-Za-z0-9_.-]+)$")


def _pair_expr(task: str, param: str, provider: str) -> str:
    """Expression for a routed upstream's output: exactly one twin ran, the
    other is Skipped and its outputs resolve to their defaults — pick the
    twin that ran."""
    return ("tasks['%s'].status == 'Skipped' ? tasks['%s-%s'].outputs."
            "parameters['%s'] : tasks['%s'].outputs.parameters['%s']"
            % (task, task, provider, param, task, param))


def _cmd_json(cmd: list, routed=(), provider: str = "") -> str:
    """Render the step-command as a JSON array that STAYS valid JSON after
    Argo's parameter substitution.

    References to a routed upstream's outputs are pair-aware (`_pair_expr`):
    a twin whose upstream ALSO ran on HPC must read the upstream twin, not
    the Skipped in-cluster task (observed at run time: a GPU step on
    MeluXina got --training-result "" and fine-tuned the base weights).

    A naive json.dumps breaks at run time (observed at run time): Argo
    substitutes {{workflow.parameters.X}} / {{tasks.X.outputs.parameters.Y}}
    INSIDE the already-serialized string, and a multi-line value (the
    compose-and-validate params.yaml output is a whole YAML doc) lands raw
    newlines/quotes inside a JSON string — the submit pod's json.loads dies
    on 'invalid control character'. Fix: tokens carrying substitutable tags
    are emitted as {{=toJson(...)}} expressions, so Argo itself JSON-escapes
    the substituted value; literal tokens stay json.dumps'd. Mixed tokens
    rebuild the full string inside the expression via single-quoted
    concatenation."""
    parts = []
    for tok in cmd:
        if not _SUBST_TAG.search(tok):
            parts.append(json.dumps(tok))
            continue
        exprs, pos = [], 0
        for m in _SUBST_TAG.finditer(tok):
            if m.start() > pos:
                exprs.append("'%s'" % tok[pos:m.start()].replace("\\", "\\\\").replace("'", "\\'"))
            ref = _TASK_OUTPUT.match(m.group(1))
            if ref and ref.group(1) in routed:
                exprs.append(("(%s)", _pair_expr(ref.group(1), ref.group(2), provider)))
            else:
                exprs.append(_tag_expr(m.group(1)))
            pos = m.end()
        if pos < len(tok):
            exprs.append("'%s'" % tok[pos:].replace("\\", "\\\\").replace("'", "\\'"))
        # a ternary needs parentheses only when concatenated with literals
        exprs = [(e[0] % e[1] if len(exprs) > 1 else e[1]) if isinstance(e, tuple) else e
                 for e in exprs]
        parts.append("{{=toJson(%s)}}" % " + ".join(exprs))
    return "[" + ", ".join(parts) + "]"


DEFAULT_TIME_LIMIT_MINUTES = 240
# Argo budget on top of the Slurm limit: the twin pod also waits in the
# MeluXina queue (evening waits run to hours), builds the SIF and stages the
# dataset in before the job's own clock starts. If the twin's deadline fires
# first, on_term leaves a RUNNING job to finish unobserved — so the deadline
# must comfortably exceed queue + prep + time limit.
QUEUE_ALLOWANCE_MINUTES = 480
# PRD-HPC-1461 D-44: a step that saves on the stop signal continues in a new job,
# at most this many times (MAX_CONTINUATIONS in the waiter). Each job may queue,
# prepare and run again, so the waiter's deadline covers all of them.
HPC_MAX_CONTINUATIONS = 5
HPC_ANNOTATION = "platform.kubecore.io/hpc"
# step(resumable=...): how long before its wall time the step is told to save (D-44 as amended
# 2026-11-05). Only resumable steps get the signal and continue.
HPC_RESUMABLE_ANNOTATION = "platform.kubecore.io/hpc-resumable"
# How the kubelet words a waiter pod lost with its node: Argo marks such a pod
# Failed (a pod with a status message is never an Error), so OnError alone
# never retries a Spot preemption or a node-pressure eviction.
POD_LOSS_MESSAGES = ("imminent node shutdown|node is shutting down|node is draining"
                     "|The node was low on resource|The node had condition"
                     "|Pod was rejected|Evicted|evicted|pod deleted|Pod was deleted")
POD_LOSS_RETRY = ("lastRetry.status == 'Error' or lastRetry.message matches '.*(%s).*'"
                  % POD_LOSS_MESSAGES)


def sharing_env(ctx: dict) -> list:
    """PRD-1609 node sharing, as the operator published it in pipeline-context hpc.*
    (sharing: on, scope: the project's hash). Nothing is added unless it is on, so a
    project without sharing renders the waiter exactly as before."""
    hpc = ctx.get("hpc") or {}
    # "on" as the operator renders it (quoted); a YAML 1.1 reader turns a bare on into True.
    if hpc.get("sharing") not in ("on", True) or not hpc.get("scope"):
        return []
    return [{"name": "HPC_SHARING", "value": "on"},
            {"name": "HPC_SCOPE", "value": str(hpc["scope"])}]


def controller_serves(ctx: dict) -> bool:
    """PRD-HPC-1461 D-58/D-63: the operator publishes hpc.controller "serve" once the pool's
    controller serves the project. The twin is then the credential-free follower. Any other value (or
    none) means the controller does not serve the project and the twin refuses (refusal_template)."""
    return (ctx.get("hpc") or {}).get("controller") == "serve"


def follower_template(ctx: dict, tpl: dict, provider: str, dataset: str) -> dict:
    """The `meluxina-run` template as the follower (PRD-HPC-1461 D-59): it creates the step's
    HPCArgoWorkflowJob, prints its progress and writes the Argo outputs from its status. It holds no
    Slurm, staging or MLflow credential and no Secret volume: the controller's runner Job carries them,
    and the endpoints come from the runner's trusted ConfigMap, not from here. Inputs, outputs, deadline,
    retry and labels are `tpl`'s (the shared base from enhance_hpc)."""
    image = (ctx.get("hpc") or {}).get("followerImage")
    if not image:
        raise ValueError("meluxina: pipeline-context hpc.controller is 'serve' but hpc.followerImage is "
                         "missing — the operator publishes the kaos-hpc-operator image there")
    env = [
        {"name": "HPC_JOB_NAMESPACE", "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}}},
        {"name": "WF_NAME", "value": "{{workflow.name}}"},
        {"name": "WF_UID", "value": "{{workflow.uid}}"},
        {"name": "STEP_NAME", "value": "{{inputs.parameters.step-name}}"},
        # The twin's DAG task name: unique per task in the entrypoint DAG, and the same on every Argo
        # retry of the twin (a retry is a new pod of the same task; only Argo's node name gets a
        # "(n)" suffix, which is not in this parameter). The job name derives from it and WF_UID.
        {"name": "NODE_KEY", "value": "{{inputs.parameters.step-name}}-%s" % provider},
        {"name": "IMAGE_REF", "value": "{{inputs.parameters.image}}"},
        {"name": "STEP_COMMAND", "value": "{{inputs.parameters.step-command}}"},
        {"name": "SLURM_TIME_LIMIT", "value": "{{inputs.parameters.time-limit}}"},
        {"name": "HPC_CLASS", "value": "{{inputs.parameters.hpc-class}}"},
        {"name": "HPC_RESUMABLE_LEAD", "value": "{{inputs.parameters.resumable-lead}}"},
        {"name": "HPC_RESUMABLE", "value": "{{inputs.parameters.resumable}}"},
        # step(idle_timeout=...): minutes, "0" = off, "" = the platform's 20 (D-72); the follower copies it
        # to the job's idleTimeoutMinutes. The same annotation drives the in-cluster idle watchdog.
        {"name": "HPC_IDLE_TIMEOUT_MINUTES", "value": "{{inputs.parameters.idle-timeout}}"},
        {"name": "HPC_MAX_CONTINUATIONS", "value": str(HPC_MAX_CONTINUATIONS)},
        {"name": "STEP_OUTPUTS", "value": "{{inputs.parameters.step-outputs}}"},
        {"name": "DATASET", "value": dataset},
        # The only spec env the controller admits (allowlist).
        {"name": "OUTPUTS_REPO", "value": outputs_repo(ctx)},
        {"name": "OUTPUTS_REF", "value": OUTPUTS_REF},
        {"name": "CHECKPOINT_BUCKET", "value": outputs_repo(ctx)},
        {"name": "CHECKPOINT_PREFIX", "value": checkpoint_prefix()},
    ] + ([{"name": KAOS_LIB_SUPPORT_ENV, "value": support_value(ctx)}] if support_value(ctx) else []) \
      + sharing_env(ctx)
    follower = dict(tpl)
    follower["container"] = {"image": str(image), "command": ["/follower"], "env": env}
    return follower


# What the twin says when the pool's HPC controller does not serve the project (F-35: there is no
# in-pod fallback). Shown in the step's log and as the workflow's failure; the text names the fix.
HPC_NOT_SERVED_MESSAGE = ("MeluXina steps run through the pool's HPC controller, which does not serve this "
                          "project: enable operators.hpc on the pool (KubePool spec.operators.hpc) and wait "
                          "until the project's MeluXina budget is known, or pick an in-cluster class. "
                          "Nothing was submitted.")


def refusal_template(tpl: dict) -> dict:
    """The `meluxina-run` template for a project the controller does not serve (PRD-HPC-1461 F-35).
    It only prints HPC_NOT_SERVED_MESSAGE and fails, so the run stops with a clear reason; it holds no
    credential, never submits to the site and is not retried. The template still renders (rather than
    failing the whole pipeline's render) because the author may never pick a MeluXina class; the
    refusal happens only when one is picked. Inputs, outputs and labels are `tpl`'s."""
    refusal = {k: v for k, v in tpl.items() if k not in ("retryStrategy", "activeDeadlineSeconds")}
    refusal["container"] = {"image": "python:3.12-alpine", "command": ["sh", "-c"],
                            "args": ["echo \"$HPC_NOT_SERVED\" >&2; exit 1"],
                            "env": [{"name": "HPC_NOT_SERVED", "value": HPC_NOT_SERVED_MESSAGE}]}
    return refusal


def parse_time_limit(value) -> int:
    """'90' / '90m' -> 90 minutes, '12h' -> 720. Raises ValueError otherwise."""
    text = str(value).strip()
    m = re.match(r"^([0-9]+)([mh]?)$", text)
    if not m or int(m.group(1)) == 0:
        raise ValueError(
            "%s=%r: expected minutes or hours like '90m', '12h' or '720'"
            % (HPC_ANNOTATION, value))
    minutes = int(m.group(1))
    return minutes * 60 if m.group(2) == "h" else minutes


RESUMABLE_OFF = "off"   # step(resumable=False): never continued from a checkpoint


def step_idle_timeout(step: dict) -> str:
    """The step's idle_timeout in minutes as text ("0" = off), or "" for the platform default."""
    raw = ((step.get("metadata") or {}).get("annotations") or {}).get("platform.kubecore.io/idle-timeout")
    return str(raw) if raw is not None else ""


def step_resumable_opt_out(step: dict) -> bool:
    """True when the step declared resumable=False (the follower then sets HPC_RESUMABLE=0, which the
    controller maps to HPCArgoWorkflowJob spec.resumableOptOut)."""
    raw = ((step.get("metadata") or {}).get("annotations") or {}).get(HPC_RESUMABLE_ANNOTATION)
    return raw == RESUMABLE_OFF


def step_resumable_lead(step: dict) -> int:
    """Minutes before the wall time a resumable step gets the stop signal; 0 when it is not resumable
    or opted out."""
    raw = ((step.get("metadata") or {}).get("annotations") or {}).get(HPC_RESUMABLE_ANNOTATION)
    return parse_time_limit(raw) if raw not in (None, "", RESUMABLE_OFF) else 0


def step_time_limit(step: dict) -> int:
    """Slurm wall-clock minutes for a routed step (annotation or default)."""
    raw = ((step.get("metadata") or {}).get("annotations") or {}).get(HPC_ANNOTATION)
    return parse_time_limit(raw) if raw not in (None, "") else DEFAULT_TIME_LIMIT_MINUTES


HPC_CLASS_PREFIX_FMT = "%s-"  # class names are provider-prefixed: meluxina-gpu


def hpc_classes(ctx: dict) -> list:
    """The HPC compute classes the account can use, from the pipeline
    context (k8smlapp composition, gated on hpcReady). Each entry:
    {name, tier, partition, qos, gpus, cpus, memoryGiB, description}."""
    hpc = ctx.get("hpc") or {}
    if not hpc.get("enabled"):
        return []
    return [dict(c) for c in (hpc.get("classes") or []) if c.get("name")]


def _when_expr(when: str) -> str:
    """Translate a simple-tag `when` ({{workflow.parameters.X}} == Y / != Y)
    into an Argo expression; an expression `when` ({{=...}}) is passed
    through. Anything else fails the render loudly: a silently dropped gate
    would run a step the author disabled."""
    w = (when or "").strip()
    if not w:
        return ""
    if w.startswith("{{=") and w.endswith("}}"):
        return w[3:-2].strip()
    m = re.match(r"^\{\{\s*workflow\.parameters\.([A-Za-z0-9_.-]+)\s*\}\}\s*(==|!=)\s*(\S+)$", w)
    if not m:
        raise ValueError(
            "meluxina: cannot combine the step's when %r with the HPC class gate — "
            "use {{workflow.parameters.X}} == Y / != Y or an {{= expression }}" % when)
    param, op, value = m.groups()
    value = value.strip("'\"")
    return "workflow.parameters['%s'] %s '%s'" % (param, op, value)


def enhance_hpc(spec: dict, ctx: dict, steps: list, gpu_step_names: set) -> None:
    """Per-step HPC placement. Every step's
    {step}-class dropdown carries the HPC classes (enhance_class_param);
    here each un-pinned step gets a Slurm twin, and the pair is gated on
    the chosen class: in-cluster when the class is not HPC, twin when it is.
    A step's own `when` is preserved on both."""
    classes = hpc_classes(ctx)
    if not classes:
        return
    provider = (ctx.get("hpc") or {}).get("provider", "meluxina")
    prefix = HPC_CLASS_PREFIX_FMT % provider
    by_class = {c["name"]: c for c in classes}

    # The global `target` switch is gone: placement is per step.
    parameters = spec["arguments"]["parameters"]
    parameters[:] = [p for p in parameters if p.get("name") != "target"]

    entry = spec.get("entrypoint")
    dag_tpl = next((t for t in spec.get("templates", [])
                    if t.get("name") == entry and "dag" in t), None)
    if dag_tpl is None:
        return
    tasks = dag_tpl["dag"]["tasks"]
    by_tpl = {s["name"]: s for s in steps}

    def _routable(task):
        step = by_tpl.get(task.get("template"))
        annots = ((step or {}).get("metadata") or {}).get("annotations") or {}
        # pinned to one in-cluster class: no HPC twin
        return step is not None and "platform.kubecore.io/compute-class" not in annots

    routable = {t["name"] for t in tasks if _routable(t)}
    routed = []
    outputs_union: set = set()
    for task in list(tasks):
        if task["name"] not in routable:
            continue
        step = by_tpl[task["template"]]
        class_param = "workflow.parameters['%s-class']" % step["name"]
        own = _when_expr(task.get("when", ""))
        hpc_gate = "hasPrefix(%s, '%s')" % (class_param, prefix)
        task["when"] = "{{=%s!%s}}" % ("(%s) && " % own if own else "", hpc_gate)
        twin_when = "{{=%s%s}}" % ("(%s) && " % own if own else "", hpc_gate)
        container = step.get("container") or {}
        argmap = {p.get("name"): str(p.get("value", ""))
                  for p in ((task.get("arguments") or {}).get("parameters")
                            or [])}
        cmd = [re.sub(r"\{\{\s*inputs\.parameters\.([A-Za-z0-9_.-]+)\s*\}\}",
                      lambda m: argmap.get(m.group(1), ""), tok)
               for tok in ((container.get("command") or [])
                           + (container.get("args") or []))]
        cmd = [t for t in cmd
               if t and "{{inputs." not in t and "{{item" not in t]
        minutes = step_time_limit(step)
        lead = step_resumable_lead(step)
        if lead >= minutes:
            raise ValueError("step %s: resumable lead %d min is not shorter than its wall time %d min"
                             % (step["name"], lead, minutes))
        # Resumability is discovered (D-74): the controller may continue ANY step that is not opted out
        # (resumable=False), up to (1 + HPC_MAX_CONTINUATIONS) jobs, each queuing, preparing and running
        # again, so the waiter's Argo deadline must cover all of them or Argo would cut a continuing step.
        # Only an opted-out step runs one job and keeps a one-job deadline.
        jobs = 1 if step_resumable_opt_out(step) else 1 + HPC_MAX_CONTINUATIONS
        step_outputs = [o["name"] for o in
                        ((step.get("outputs") or {}).get("parameters") or [])]
        outputs_union.update(step_outputs)
        twin = {
            "name": task["name"] + "-" + provider,
            "template": "meluxina-run",
            "when": twin_when,
            "arguments": {"parameters": [
                {"name": "step-name", "value": task["name"]},
                {"name": "image", "value": container.get("image", "")},
                {"name": "step-command",
                 "value": _cmd_json(cmd, routed=routable, provider=provider)},
                {"name": "time-limit", "value": str(minutes)},
                {"name": "deadline-seconds",
                 "value": str(jobs * (minutes + QUEUE_ALLOWANCE_MINUTES) * 60)},
                {"name": "resumable-lead", "value": str(lead)},
                # "0" = resumable=False; "auto" lets the controller discover resumability (D-74)
                {"name": "resumable", "value": "0" if step_resumable_opt_out(step) else "auto"},
                {"name": "idle-timeout", "value": step_idle_timeout(step)},
                {"name": "step-outputs", "value": ",".join(step_outputs)},
                {"name": "hpc-class", "value": "{{workflow.parameters.%s-class}}" % step["name"]},
            ]},
        }
        if task.get("depends"):
            twin["depends"] = task["depends"]
        # Right after its in-cluster task, not at the end: the Argo UI's
        # template graph needs every dependency listed above its dependent,
        # and later steps depend on both twins (crashes reading 'genre').
        tasks.insert(tasks.index(task) + 1, twin)
        routed.append(task["name"])

    if not routed:
        return

    # F-05: downstream steps consume {{tasks.<routed>.outputs.parameters.P}}.
    # Exactly one twin ran; the other is Skipped and its outputs resolve to
    # their declared defaults ("{}"). Pick the twin that actually ran.
    def _pick(m):
        return "{{=%s}}" % _pair_expr(m.group(1), m.group(2), provider)
    ref_re = re.compile(r"\{\{\s*tasks\.(%s)\.outputs\.parameters\.([A-Za-z0-9_.-]+)\s*\}\}"
                        % "|".join(re.escape(r) for r in routed))
    for task in tasks:
        if task["name"].endswith("-" + provider):
            continue
        for p in ((task.get("arguments") or {}).get("parameters") or []):
            v = p.get("value")
            if isinstance(v, str) and ref_re.fullmatch(v.strip()):
                p["value"] = ref_re.sub(_pick, v.strip())

    # A bare task token in Argo depends grammar means Succeeded; a routed dep
    # is now a twin pair where exactly one twin runs and the other is Skipped.
    # Twins included: a twin whose upstream also ran on HPC must depend on
    # the upstream PAIR, not on the (Skipped) in-cluster task.
    # Status-qualified references (step.Succeeded || step.Skipped
    # || step.Omitted) must name the twin too: Argo exposes tasks.X to
    # a task's expressions ONLY for X in its depends, so a consumer whose
    # args pick tasks['X-meluxina'] hangs forever with "tasks.X-meluxina is
    # missing" (observed at run time, argo v4.0.6). Pair semantics:
    # Succeeded/Failed/Errored/Daemoned = either twin; Skipped/Omitted = both.
    def _status_pair(r):
        def sub(m):
            st = m.group(1)
            op = "&&" if st in ("Skipped", "Omitted") else "||"
            return "(%s.%s %s %s-%s.%s)" % (r, st, op, r, provider, st)
        return sub

    for task in tasks:
        dep = task.get("depends")
        if not dep:
            continue
        for r in routed:
            if task["name"] in (r, r + "-" + provider):
                continue
            dep = re.sub(r"(?<![\w.-])%s\.(Succeeded|Skipped|Omitted|Failed|Errored|Daemoned)(?![\w.-])"
                         % re.escape(r), _status_pair(r), dep)
            pair = ("((%s.Succeeded || %s.Skipped) && "
                    "(%s-%s.Succeeded || %s-%s.Skipped))"
                    % (r, r, r, provider, r, provider))
            dep = re.sub(r"(?<![\w.-])%s(?![\w.-])" % re.escape(r), pair, dep)
        task["depends"] = dep

    # The pipeline's `dataset` workflow parameter (`<dataset-repo>@<version>`) is
    # handed to the follower, which passes it on in the job spec; no param -> no
    # stage-in, the step runs data-less.
    wf_params = {p.get("name") for p in parameters}
    dataset = ("{{workflow.parameters.dataset}}"
               if "dataset" in wf_params else "")
    tpl = {
        "name": "meluxina-run",
        "inputs": {"parameters": [
            {"name": "step-name"}, {"name": "image"}, {"name": "step-command"},
            {"name": "time-limit"}, {"name": "deadline-seconds"},
            {"name": "step-outputs", "value": ""}, {"name": "hpc-class"},
            {"name": "resumable-lead", "value": "0"}, {"name": "resumable", "value": "auto"},
            {"name": "idle-timeout", "value": ""}]},
        # Per-step: Slurm time limit + queue/prep allowance (see
        # QUEUE_ALLOWANCE_MINUTES). Argo resolves the parameter here.
        "activeDeadlineSeconds": "{{inputs.parameters.deadline-seconds}}",
        # A lost follower pod (node preemption, eviction, deletion) is not a
        # step failure: retry it - the job's name is deterministic (workflow UID
        # + step), so the retried follower re-attaches to the same
        # HPCArgoWorkflowJob instead of creating a duplicate. A job that failed
        # on MeluXina is not retried.
        "retryStrategy": {"limit": "2", "retryPolicy": "Always",
                          "expression": POD_LOSS_RETRY},
        "metadata": {"labels": {"platform.kubecore.io/compute-type": "hpc",
                                "platform.kubecore.io/hpc-class": "{{inputs.parameters.hpc-class}}"}},
        # slurm-job-id plus the union of every routed step's declared outputs
        # (one shared template; each twin fills its own, the rest default).
        "outputs": {"parameters": [{"name": "slurm-job-id",
                                    "valueFrom": {"path": "/tmp/slurm-job-id"}}]
                    + [{"name": n, "valueFrom": {"path": "/tmp/outputs/%s.json" % n,
                                                 "default": "{}"}}
                       for n in sorted(outputs_union)]},
    }
    # F-35: the controller's follower, or a refusal; never an in-pod submitter.
    tpl = follower_template(ctx, tpl, provider, dataset) if controller_serves(ctx) else refusal_template(tpl)
    spec["templates"].append(tpl)
