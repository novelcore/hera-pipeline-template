# Run on HPC (Slurm)

**Goal:** one step of a run executes on an HPC (Slurm) supercomputer, for example training on its
A100 GPUs, while the other steps stay on your project's own machines. Today the HPC provider is MeluXina, Luxembourg's supercomputer.

**Who can do it:** anyone who can submit runs (`dev`, `ops`, `admin`), on a project with an **HPC (Slurm)** environment. Your platform contact connects a project to HPC. The project then uses the
organisation's HPC allocation.

## Pick an HPC class for a step

On the submit form, every step has a `<step>-class` dropdown. On a project with HPC (Slurm) it also offers:

| class | machine | typical use |
|---|---|---|
| `meluxina-gpu` | 4× A100-40GB, 2× EPYC 7452, 512 GB | training |
| `meluxina-cpu` | 2× EPYC 7452 (128 cores), 512 GB | heavy CPU work |
| `meluxina-largemem` | 4 TB RAM | data that does not fit a node |

HPC class names start with `meluxina-`, the provider's name. Pick one for one step, for example `model-training-class` = `meluxina-gpu`, and submit. There is no
global switch: each step of each run is placed on its own. A step pinned to a class in
`pipeline.py` (a `compute-class` annotation) always stays on your project's own machines.

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
   lakeFS are reached with a short-lived token minted for each job.

Nothing in your code changes. While the job waits, the step's log shows its state and the
queue's reason for holding it. If you stop or delete the run, the platform cancels the HPC job.

## Set a time limit

Slurm stops a job at its wall-clock limit. The default is 4 hours. Give long steps their own limit
in `pipeline.py`:

```python
train = step("model-training", gpu=True, needs=[load], walltime="12h",
             reads=["experiment", "dataset", "train"])
```

The value takes minutes or hours: `"90m"`, `"12h"`, or `"720"` (minutes). `hpc_time_limit` is the older name and
still works. The platform adds a queue allowance on top for its own wait, for every continuation a step may need (a step with `resumable=False` gets one job's).

For a short step (up to 2 hours) that has finished a few times, the platform asks the site for a time limit based on
those runs, which starts it sooner. If such a step is cut short anyway, it is run again once at your limit, so it is
never stopped where your limit would have passed. Long steps keep the limit you set.

### Long runs continue after the time limit

A step that keeps its checkpoints in the folder `KAOS_CHECKPOINT_DIR` (or uses `kaos_lib`'s framework hooks for
Ultralytics, Lightning or Hugging Face) continues in a new job from its last checkpoint when the time limit, a node
failure or maintenance ends a job. You do not mark the step: there is nothing to declare and no code to write. See
[When a machine is lost or a time limit hits](resilience.md).

A continued job waits in the queue again and its time counts against your budget, up to 5 continuations per step. A
continuation that does not get past the previous checkpoint ends with the reason `NoProgress`. A step that writes no
checkpoint ends at its limit with a message that names the limit; if the node fails it is run again from the start, at
most twice. A step that hangs (no GPU use and no new log lines for 20 minutes) ends with the reason `Idle`
(`idle_timeout="40m"` changes the window, `idle_timeout=0` turns it off; the same setting applies on your project's own machines).

On your project's own machines the same folder is kept safe by the platform too, so the same step code runs everywhere.
`resumable="30m"` stays available to be signalled earlier before the time limit when a checkpoint is large.

## What you should see

- The step's log shows its Slurm job, then your step's own output.
- The run continues to the next step when the job ends.
- The lakeFS Datasets page has an **HPC** tab, and the console's Datasets page can filter by
  location (verify what each shows for your project).

## If it isn't there

| symptom | fix |
|---|---|
| no `meluxina-*` in the dropdown | the project has no HPC (Slurm) environment yet; ask your KAOS contact |
| the step waits for hours | the queue is busy; this is the HPC queue, not your run |
| the step stops at its time limit | raise `walltime`, or write its checkpoints into `KAOS_CHECKPOINT_DIR` so it continues ([details](resilience.md)) |
| the step ends with `Idle` | it showed no GPU use and no new log lines for 20 minutes; raise `idle_timeout` if it was working |
| the step ends with `NoProgress` | the continuation did not get past its checkpoint: check that loading restores your epoch counter |
| a large checkpoint is not saved in time before the limit | `resumable="30m"` signals the step earlier, or save less (weights only) |
| the job is refused or never starts | the HPC allocation may be used up or not cover that class; ask your KAOS contact |
| a lost waiting pod | it is retried twice and re-attaches to the same Slurm job; a job that failed on HPC is not retried |

DEVELOPER.md §8.1 and §8.2 have the details for template maintainers.
