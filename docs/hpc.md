# Run on HPC (Slurm)

**Goal:** one step of a run executes on an HPC (Slurm) supercomputer, for example training on its
A100 GPUs, while the other steps stay on your project's own machines. An HPC (Slurm) provider is, for example, MeluXina.

**Who can do it:** anyone who can submit runs (`dev`, `ops`, `admin`), on a project with an **HPC (Slurm)** environment. Your platform contact connects a project to HPC. The project then uses the
organisation's HPC allocation.

## Pick an HPC class for a step

On the submit form, every step has a `<step>-class` dropdown. On a project with HPC (Slurm) it also offers:

| class | machine | typical use |
|---|---|---|
| `meluxina-gpu` | 4× A100-40GB, 2× EPYC 7452, 512 GB | training |
| `meluxina-cpu` | 2× EPYC 7452 (128 cores), 512 GB | heavy CPU work |
| `meluxina-largemem` | 4 TB RAM | data that does not fit a node |

Pick one for one step, for example `model-training-class` = `meluxina-gpu`, and submit. There is no
global switch: each step of each run is placed on its own. A step pinned to a class in
`pipeline.py` (a `compute-class` annotation) always stays on your project's own machines.
You never choose a Slurm queue or quality-of-service: the platform picks the lane and the time limit
for you (see [Set a time limit](#set-a-time-limit)).

The read-only `pipeline-info` field at the top of the form lists the classes and the HPC
account the run uses.

## What happens

1. The step waits in the HPC Slurm queue. The run shows it as running while it waits, for
   minutes to hours depending on how busy the partition is.
2. Before the job starts, the platform **stages the dataset commit** on the HPC cluster's Lustre storage.
   It does this once per version, and a new version copies only what changed. The step's
   `datasets.materialize(...)` uses the staged copy.
3. The job runs **your step image**, converted to an Apptainer image (cached), with the same command
   it runs on your project's own machines.
4. The step writes its results with the same run writer, so its commit appears in `outputs-<app>`
   exactly as for a step on your project's own machines. Its declared outputs reach the next step as usual. MLflow and
   lakeFS are reached for you: the step needs no credentials.

Nothing in your code changes. While the job waits, the step's log shows its state and the
queue's reason for holding it. If you stop or delete the run, the platform cancels the HPC job.

### Several steps on one node

An HPC node has several GPUs (for example 4). Steps that run at the same time, in the same project and on the same
HPC class, share nodes: each step gets its own GPU and its own share of the node's CPUs and memory, so four 1-GPU
steps use one node instead of four. This also holds for resumable steps: each one is told to save its progress at
its own time. Your code needs nothing for this: compute only on the GPU the step is given (`CUDA_VISIBLE_DEVICES`).
A shared node is counted once against your allocation, not once per step.

If a job waits in the queue longer than its credentials last, the platform submits it again with fresh ones. It
then waits in the queue anew; the step's status records each time this happened.

## Set a time limit

Slurm stops a job at its wall-clock limit. The default is 4 hours. Give long steps their own limit
in `pipeline.py` with `hpc_time_limit` (only on `gpu=True` steps):

```python
train = step("model-training", gpu=True, hpc_time_limit="12h",
             reads=["experiment", "dataset", "train"])
```

The value is a string of minutes or hours: `"90m"`, `"12h"`, or `"720"` (minutes). The platform adds a
queue allowance on top for its own wait, for every continuation a step may need (a step with
`resumable=False` gets one job's).

You do not pick a queue. The platform chooses the lane and may ask the site for a shorter limit than
yours: for a short step (up to 2 hours) that has finished a few times, it uses a limit learned from
those runs, which starts it sooner. If such a step is cut short anyway, it is run again once at your
limit, so it is never stopped where your limit would have passed. Long steps keep the limit you set.

### Long runs continue after the time limit

A step that keeps its checkpoints in the folder `KAOS_CHECKPOINT_DIR` (or uses `kaos_lib`'s framework hooks for
Ultralytics, Lightning or Hugging Face) continues in a new job from its last checkpoint when the time limit, a node
failure or maintenance ends a job. See [When a machine is lost or a time limit hits](resilience.md).

There are two ways a step counts as *resumable*:

- **You declare it.** `resumable=True`, or a lead time such as `resumable="3m"`: how long before the time limit
  the step is told to save (default 10 minutes; it must be shorter than the time limit, and the step must be
  `gpu=True`). The step writes its state with `checkpoint.save` / `checkpoint.load` (or a framework hook).
- **The platform learns it.** When an earlier continuation of the step loaded its checkpoint and got further than
  it, the platform treats the step as resumable from then on, with nothing declared.

`resumable=False` opts a step out: it is never continued from a checkpoint.

A continued job waits in the queue again and its time counts against your budget, up to 5 continuations per step. A
continuation that does not get past the previous checkpoint ends with the reason `NoProgress`. A step that writes no
checkpoint ends at its limit with a message that names the limit; if the node fails it is run again from the start, at
most twice. A step that hangs (no GPU use and no new log lines for 20 minutes) ends with the reason `Idle`
(`idle_timeout="40m"` changes the window, `idle_timeout=0` turns it off; the same setting applies on your project's own machines).

**A step longer than the longest run the site allows** (for example `hpc_time_limit="5d"` where one job may run
2 days):

- if it is resumable, it runs as a series of capped attempts, each up to the longest run, each continuing from the
  checkpoint. The log says "declared N min runs as continuations of up to M min each". It is refused only when it
  would need more than the 5 continuations allow (reason `TooLongBeyondContinuations`).
- if it is not resumable, it is refused before it is submitted, with the reason `TooLongNotResumable`. The message
  gives your limit, the maximum, and the two fixes: make the step resumable, or shorten it.

## Why a step is waiting or refused

While a step waits, its log shows its state and the reason. These are the ones you may meet:

| reason | what it means | what to do |
|---|---|---|
| `WaitingForBudget` | the project's allocation has enough left, but part of it is held by running steps | wait: it starts when they finish |
| `ConcurrencyLimit` | your project is running as many HPC jobs as it may | wait: a slot frees up when one ends |
| `BudgetBlocked` | the step needs more node-hours than your project's own share has left this month | shorten the step, or ask your KAOS contact for more share |
| `SiteLimit` | the site's monthly limit on the account has run out (also shown while a submitted job queues behind that limit) | ask your KAOS contact |
| `SubmitLimit` | the site allows only so many queued and running jobs per user, and the project already has that many. The step **fails** at once instead of waiting | run it again when some jobs have finished |
| `TooLongNotResumable`, `TooLongBeyondContinuations` | the time limit is longer than the site allows (see above) | make it resumable, or shorten it |
| `InvalidImage` | the step's image reference is incomplete (no registry or repository), so it cannot be pulled. The step fails before anything is submitted, and nothing is charged | run it again after the app's next build; if it repeats, ask your KAOS contact |
| `GPUViolation` | on a node shared by several steps, this step used a GPU that was not its own. Only that step is stopped | compute only on the GPU the step is given: do not override the GPU selection or hard-code a device number |

A project has a separate allocation for each kind of machine: GPU, CPU, FPGA and large memory. One that is used up
blocks only the steps that use it: a project out of CPU hours can still run its GPU steps. A used-up allocation's
class is not offered in the run form until it is topped up. When a project has spent most of its monthly allocation
(80% by default), the platform raises a budget warning for the project before steps start being refused.

## What you should see

- The step's log shows its Slurm job, then your step's own output.
- The run continues to the next step when the job ends.

## If it isn't there

| symptom | fix |
|---|---|
| no `meluxina-*` in the dropdown | the project has no HPC (Slurm) environment yet, or that class's allocation is used up this month; ask your KAOS contact |
| the step waits for hours | the queue is busy; this is the HPC queue, not your run |
| the step stops at its time limit | raise `hpc_time_limit`, or write its checkpoints into `KAOS_CHECKPOINT_DIR` so it continues ([details](resilience.md)) |
| the step ends with `Idle` | it showed no GPU use and no new log lines for 20 minutes; raise `idle_timeout` if it was working |
| the step ends with `NoProgress` | the continuation did not get past its checkpoint: check that loading restores your epoch counter |
| a large checkpoint is not saved in time before the limit | `resumable="30m"` signals the step earlier, or save less (weights only) |
| the step is refused with `TooLongNotResumable` | make it resumable (see above) or shorten `hpc_time_limit` |
| the job is refused or never starts | read the reason in the step's log: [Why a step is waiting or refused](#why-a-step-is-waiting-or-refused) |
| the step's own log goes quiet while it waits | the run keeps following the same Slurm job; a job that failed on HPC is not retried |

The [Pipeline Developer Guide](https://github.com/novelcore/hera-pipeline-template/blob/dev/DEVELOPER.md) (§8) has the short version.
