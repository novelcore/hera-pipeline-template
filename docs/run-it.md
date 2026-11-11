# Run your pipeline

**Goal:** a run started from the form and watched until it finishes.
[Chapter 7](cookbook/7-run-it.md) has the full field list, retries and resume.

## 1. Open the form

Console → **Pipelines** → your app → **Run**.

![The submit panel for the pipeline, with the Submit button](img/submit-form.png)

## 2. Set the fields, or keep the defaults

Every field came from your `config/` folder, plus a few the platform adds:

- `pipeline-info` at the top is a read-only note. Leave it.
- `experiment-name` and every other setting in `config/`, with dots turned into dashes.
- **`dataset`**: a dropdown of your project's datasets and versions, such as `dataset-cats@v2`, and
  of datasets shared with your project, such as `team-a/dataset-cats@v3`
  ([Datasets](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/datasets.html)).
- `<step>-class` for each step: the kind of machine it runs on, including the HPC classes on a
  project with HPC (Slurm) ([Run on HPC (Slurm)](hpc.md)).
- `<step>-cpu`, `<step>-mem` and `<step>-disk` to ask for less, for a quick test.

![The experiment fields on the submit form](img/form-experiment-fields.png)

![Per step sizing fields for each step](img/per-step-sizing.png)

## 3. Submit and watch

Click **Submit**. The run page shows the run as boxes, one per step: blue while running, green when done,
red when failed, and grey for *skipped* (its `when=` condition was false).

![A finished run, every step green](img/argo-running.png)

Click a box, then **Logs**, to read what the step printed. Read the last lines of a red step first.
You can close the tab: the run continues.

## Where results go

- Files your steps write go to your app's `outputs-<app>` repository in lakeFS: one commit per step
  per run, under `checkpoints/<experiment>/<run>/` ([Results](results.md)).
- Numbers a step logs go to the project's MLflow
  ([chapter 8](cookbook/8-results-and-weights.md)).

If something fails, see [When things go wrong](cookbook/10-when-things-go-wrong.md).
