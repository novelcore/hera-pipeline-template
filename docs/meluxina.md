# MeluXina

**Goal:** one step of a run executes on the MeluXina supercomputer, for example training on its
A100 GPUs, while the other steps stay on your project's own machines.

**Who can do it:** anyone who can submit runs (`dev`, `ops`, `admin`), on a project with a **Slurm (MeluXina)** environment. Your platform contact connects a project to MeluXina. The project then uses the
organisation's MeluXina allocation.

## Pick a MeluXina class for a step

On the submit form, every step has a `<step>-class` dropdown. On a project with Slurm (MeluXina) it also offers:

| class | machine | typical use |
|---|---|---|
| `meluxina-gpu` | 4× A100-40GB, 2× EPYC 7452, 512 GB | training |
| `meluxina-cpu` | 2× EPYC 7452 (128 cores), 512 GB | heavy CPU work |
| `meluxina-largemem` | 4 TB RAM | data that does not fit a node |

Pick one for one step, for example `model-training-class` = `meluxina-gpu`, and submit. There is no
global switch: each step of each run is placed on its own. A step pinned to a class in
`pipeline.py` (a `compute-class` annotation) always stays on your project's own machines.

The read-only `pipeline-info` field at the top of the form lists the classes and the MeluXina
account the run uses.

## What happens

1. The step waits in MeluXina's Slurm queue. The run shows it as running while it waits, for
   minutes to hours depending on how busy the partition is.
2. Before the job starts, the platform **stages the dataset commit** on MeluXina's Lustre storage.
   It does this once per version, and a new version copies only what changed. The step's
   `datasets.materialize(...)` uses the staged copy.
3. The job runs **your step image**, converted to an Apptainer image (cached), with the same command
   it runs on your project's own machines.
4. The step writes its results with the same run writer, so its commit appears in `outputs-<app>`
   exactly as for a step on your project's own machines. Its declared outputs reach the next step as usual. MLflow and
   lakeFS are reached with a short-lived token minted for each job.

Nothing in your code changes.

## Set a time limit

Slurm stops a job at its wall-clock limit. The default is 4 hours. Give long steps their own limit
in `pipeline.py`:

```python
train = step("model-training", gpu=True, needs=[load], hpc_time_limit="12h",
             reads=["experiment", "dataset", "train"])
```

The value takes minutes or hours: `"90m"`, `"12h"`, or `"720"` (minutes). The platform adds a queue
allowance on top for its own wait.

## What you should see

- The step's log shows its Slurm job, then your step's own output.
- The run continues to the next step when the job ends.
- The lakeFS Datasets page has a **MeluXina** tab, and the console's Datasets page can filter by
  location (verify what each shows for your project).

## If it isn't there

| symptom | fix |
|---|---|
| no `meluxina-*` in the dropdown | the project has no Slurm (MeluXina) environment yet; ask your KAOS contact |
| the step waits for hours | the queue is busy; this is MeluXina, not your run |
| the step stops at its time limit | raise `hpc_time_limit` |
| the job is refused or never starts | the MeluXina allocation may be used up or not cover that class; ask your KAOS contact |
| a lost waiting pod | it is retried twice and re-attaches to the same Slurm job; a job that failed on MeluXina is not retried |

DEVELOPER.md §8.1 has the details for template maintainers.
