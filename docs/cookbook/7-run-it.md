# 7. Run it

**Goal:** you start a run from the form, watch it, read its logs, and retry it when a step fails.

**Who can do it:** `dev`, `ops` or `admin` submit, retry and stop runs. `business` can watch.

## Open the form

Console → **Pipelines** → your app → **Run**. This opens the submit form of `<app>-pipeline` in
Argo. From Argo itself: **Workflow Templates** → `<app>-pipeline` → **Submit**.

## The fields

Every field has a default, so you can press **Submit** straight away.

| field | what it is |
|---|---|
| `pipeline-info` | a read-only note: the classes this pipeline can use and, on an HPC (Slurm) project, the HPC account. Leave it. |
| `experiment-name`, `experiment-description` | from `config/experiment.yaml`; the name groups your runs in MLflow and in `outputs-<app>` |
| `dataset` | a dropdown of `<dataset>@<version>`, newest first, including datasets shared with your project as `<owner>/<dataset>@<version>` |
| `<step>-class` | the kind of machine each step runs on: your project's classes, plus the HPC classes (`meluxina-*`) on a project with HPC (Slurm) ([Run on HPC (Slurm)](../hpc.md)) |
| `<step>-cpu`, `<step>-mem`, `<step>-disk` | ask for less than the whole machine, for a quick test |
| everything else | one field per setting in `config/`, named by its path with dashes (`train.epochs` → `train-epochs`) |

Fields that accept only some values are dropdowns. A value outside the allowed set stops the run in
its first seconds and lists the allowed values.

## Watch it

After **Submit**, Argo shows the run as a graph of steps:

- blue and spinning: running; green: done; red: failed;
- grey and *skipped*: the step's `when=` condition was false. That is normal.

Click a step, then **Logs**, to read what it printed. The first line of the template's steps is the kaos-lib
version they run (`kaos-lib 0.4.0rc20`). You can close the tab: the run keeps going. Find it again
under Argo → **Workflows**, or console → **Pipelines** → your app → **Runs in Argo**.

**You should see** every step green and, for the shipped pipeline, `[hello-world] result committed
to outputs: <commit>` at the end of the last log.

## Retry and resume

- **Retry** (on a failed run in Argo) runs the failed steps again under the **same run name**. A step
  that saves progress with kaos-lib's run writer finds what it already saved and continues from it
  ([Write results from a step](../write-a-step.md#2-save-progress-and-resume)).
- **Resubmit** starts a new run with the same field values and a new name. It starts from scratch.
- A step lost with its machine (a reclaimed spot node, a node failure) is run again by the platform, at most twice, and
  continues from its checkpoint if it kept one ([When a machine is lost](../resilience.md)). A step that fails on its own
  error is not repeated, on HPC or anywhere else.
- **Stop** ends a run. Results a step had already finished stay in `outputs-<app>`.

## If it isn't there

| symptom | fix |
|---|---|
| the run stops in seconds with "invalid value" | a field is outside its allowed values; the message lists them |
| the first step fails: the dataset or version does not exist | the message lists what exists; release a version ([chapter 5](5-your-data.md)) |
| a step stays *Pending* for a long time | no machine of that class is free yet; one may take a few minutes to appear. An HPC (`meluxina-*`) step waits in the HPC queue (minutes to hours); its log says why it waits, and [Run on HPC (Slurm)](../hpc.md#why-a-step-is-waiting-or-refused) explains each reason |
| a step is red | read the last lines of its log; [chapter 10](10-when-things-go-wrong.md) lists the usual causes |
| no **Submit** button | your role is `business`, which is read-only ([chapter 1](1-youre-in.md)) |

**Next:** [8. Results and weights](8-results-and-weights.md).
