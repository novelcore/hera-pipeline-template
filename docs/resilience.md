# When a machine is lost or a time limit hits

**Goal:** know what the platform does for you when a step is interrupted, so a long run is not lost and your code
needs no special handling.

A step can be interrupted in four ways: its machine is reclaimed (spot or preemptible nodes), the machine fails or is
drained for maintenance, an HPC (Slurm) job reaches its time limit, or the step hangs. Pipelines behave the same on
every kind of machine: your project's own cluster (GPU or CPU, spot included) and HPC.

## What happens automatically

| what happened | a step that writes checkpoints | any other step |
|---|---|---|
| machine lost, reclaimed or drained | runs again and **continues from its last checkpoint** | runs again from the start, at most twice |
| HPC time limit reached | continues from the last checkpoint in a new job | ends with a message that names the limit |
| the step hangs (no GPU use and no new log lines for 20 minutes) | on HPC, with a checkpoint it continues; on your project's own machines it ends with the reason `Idle` | ends with the reason `Idle` |
| your own code fails (a non-zero exit, out of memory, a Python error) | ends as failed: **not** repeated | ends as failed: **not** repeated |

Running a step again is always safe: a step's results are published only when it succeeds.

Nothing in your code or in `pipeline.py` is needed for this.

## Checkpoints without code

Every step gets a folder in the environment variable `KAOS_CHECKPOINT_DIR`. The platform keeps a copy of that folder
safe while the step runs (every 10 minutes by default, and when the machine is being taken away) and puts the newest
**verified** copy back before the step starts again. A copy that does not match its checksum is never used; the
previous good one is.

When your step imports `kaos_lib` (the `hello-world` step of this template does), `kaos_lib` also hooks the training
framework you already use, with nothing for you to call:

| framework | saved | on the repeated step |
|---|---|---|
| Ultralytics (YOLO) | `last.pt` at the end of each epoch, and `best.pt` once one exists | training continues, same total epochs, and `best.pt` is kept |
| PyTorch Lightning | a full Lightning checkpoint | `fit` continues from it |
| Hugging Face `Trainer` | the Trainer's `checkpoint-*` folders | `train` resumes from them |

For plain PyTorch or your own state, write into the folder yourself and resume "if the file exists":

```python
import os
ckpt = os.environ.get("KAOS_CHECKPOINT_DIR", "runs/checkpoints")   # your own default on a laptop
# torch.save(state, f"{ckpt}/last.pt") at a safe point; torch.load it at start if it exists
```

or register a save and a load function (see the kaos-lib reference). On your laptop `KAOS_CHECKPOINT_DIR` is not set and
none of this happens.

!!! note "Large checkpoints and disk"
    The folder lives on the step's machine disk. A big checkpoint (several GB) needs room: raise `disk=` for the step in
    `pipeline.py` (for example `disk="30Gi"`). Only the two newest copies are kept, and all are deleted when the step
    succeeds.

A step that may be continued is never cut by the run's own waiting budget: that budget covers up to 5 continuations, each with its queue wait. A step with `resumable=False` gets the budget of one job.

A step whose time limit is longer than the longest run the HPC site allows needs this too: if it is resumable it runs as capped attempts that continue from the checkpoint, and if it is not, it is refused before it is submitted (`TooLongNotResumable`). See [Run on HPC (Slurm)](hpc.md#long-runs-continue-after-the-time-limit).

## Settings (all optional)

Set them on the step in `pipeline.py`:

```python
train = step("model-training", gpu=True, needs=[load],
             hpc_time_limit="12h",      # HPC time limit for this step (default 4 hours)
             checkpoint_every="20m",     # copy the checkpoint folder every 20 minutes (default: 10, adapts to size)
             idle_timeout="40m")         # raise the 20-minute idle rule; 0 turns it off
```

| setting | meaning |
|---|---|
| `hpc_time_limit` | the longest the step may run on HPC (`gpu=True` steps). The platform may ask the site for less after it has seen the step finish a few times (short steps only), and runs it again at your limit if it was cut short, so a step is never stopped where your limit would have passed. |
| `checkpoint_every` | how often the folder is copied. Saving stays near 10 % of the run time: a slow save lengthens the interval. `checkpoint_every=False` turns copies off for the step (the repeat after a lost machine stays). A CPU step is copied only if you set a value here. |
| `idle_timeout` | how long a GPU step may show no GPU use (below 5 %) and no new log lines before it is ended as `Idle`. Default 20 minutes; raise it for a step with a long silent phase, or `idle_timeout=0` to turn the rule off. Same rule on HPC and on a cloud GPU node. On your project's own machines an `Idle` step is not repeated: it ends as failed. |
| `resumable` | `True` or a lead time such as `"3m"` (default 10 minutes, shorter than the time limit): the step is told to save that long before its HPC time limit; use a longer lead for a large checkpoint. Declaring it is one way to be resumable; the platform also decides on its own once an earlier continuation loaded its checkpoint and got further. `resumable=False` opts the step out: on HPC it is never continued from a checkpoint (a lost machine still re-runs it). Only for `gpu=True` steps. |

## What you will see

In the step's log:

| message | meaning |
|---|---|
| `[kaos-checkpoint] continuing from the checkpoint saved at 12:03:11 UTC (3 files)` | this is a repeat; training picks up from that copy |
| `[kaos-checkpoint] no saved checkpoint for this step: starting from the beginning` | a first run, or nothing had been saved yet |
| `[kaos-checkpoint] saved a checkpoint copy: 3 files, 212.4 MB, 4 s` | a regular copy |
| `[kaos-checkpoint] skipping checkpoint ...: the copy does not match its checksum` | a damaged copy was ignored; the previous one is used |
| `[kaos-checkpoint] could not save a checkpoint copy (...); the step is not affected` | the copy failed; the step carries on and tries again later |
| `[kaos-checkpoint] step finished; its checkpoint copies were removed` | the step succeeded and the copies were cleaned up |

In the run view, a repeated step shows its attempts one after the other (`model-training(1)`, `model-training(2)`).
On HPC the step's status line says why a job was repeated, for example that it was stopped for no GPU use and no output
for 20 minutes, or that a continuation did not get past its checkpoint (`NoProgress`): then the step ends instead of
repeating the same hours.

## If it isn't there

| symptom | fix |
|---|---|
| a repeated step starts from epoch 0 | the step wrote nothing to `KAOS_CHECKPOINT_DIR` and no framework hook applies: write there, or register save and load |
| the step ends as failed after its machine was reclaimed | the step ran out of its two repeats; run it again, or use an on-demand class for this step |
| `NoProgress` | the step restarted without loading its checkpoint, or saved the same state again: check that loading restores your epoch counter |
| copies fail with a disk message | raise `disk=` for the step |
| the step was ended as `Idle` but was working | raise `idle_timeout` for it (or `idle_timeout=0`) |
| on a cloud GPU node, the step shows `KaosIdle: ended by the idle watchdog ...` as its failure message | the platform saw no GPU use and no new log line for the window and stopped the step so the GPU stops costing money; this is the `Idle` end described above |
| a CPU step is not copied | set `checkpoint_every` on it (short CPU steps are simply repeated) |
