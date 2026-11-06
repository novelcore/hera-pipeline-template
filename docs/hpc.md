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
train = step("model-training", gpu=True, needs=[load], hpc_time_limit="12h",
             reads=["experiment", "dataset", "train"])
```

The value takes minutes or hours: `"90m"`, `"12h"`, or `"720"` (minutes). The platform adds a queue
allowance on top for its own wait.

### Long runs continue after the wall time

Declare a step resumable and it can save a checkpoint before its wall time and continue in a new job:

```python
train = step("model-training", gpu=True, needs=[load], hpc_time_limit="12h",
             resumable=True,              # or resumable="20m": the signal comes 20 minutes before the wall time
             reads=["experiment", "dataset", "train"])
```

A resumable step is told to stop 10 minutes before its wall time (or the lead you give). Your step code
decides when it is safe to save, and writes and reads its own state with `kaos_lib.checkpoint`:

```python
from kaos_lib import checkpoint

state = load_state(checkpoint.resume_path()) if checkpoint.is_resume() else fresh_state()
for epoch in range(state.epoch, epochs):
    train_one_epoch(state)
    if checkpoint.stop_requested():                               # a safe point
        checkpoint.save(lambda path: save_state(state, path))     # writes, then ends the job
```

`save_state` and `load_state` are yours: write whatever your framework needs into the folder you are given.
`save` ends the job with exit code 85. The checkpoint is uploaded to `outputs-<app>` before the job ends,
and the step continues in a new job from that checkpoint, up to 5 times. If the upload does not finish
before the wall time, the step fails instead of starting over: give a longer lead for large checkpoints.

A continued job waits in the queue again, and its time counts against your budget. On your project's own
machines no signal comes, so the same code runs to the end. A resumable step runs alone on its node.
Steps that are not resumable run to the wall time as before; one that exits 85 anyway fails.

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
| the step stops at its wall time | raise `hpc_time_limit`, or make it `resumable=True` and save with `kaos_lib.checkpoint` |
| "not continuing the step: its checkpoint did not reach the outputs repository" | the upload ran out of time: give a longer lead, `resumable="30m"`, or save a smaller checkpoint |
| "not continuing the step: ... not declared resumable" | the step exited 85: add `resumable=True` to it in `pipeline.py` |
| the job is refused or never starts | the HPC allocation may be used up or not cover that class; ask your KAOS contact |
| a lost waiting pod | it is retried twice and re-attaches to the same Slurm job; a job that failed on HPC is not retried |

DEVELOPER.md §8.1 has the details for template maintainers.
