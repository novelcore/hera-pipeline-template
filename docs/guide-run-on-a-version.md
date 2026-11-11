# Guide: run on a released version and find the result

**Goal:** a run on `dataset-cats@v1`, its result found in lakeFS and on your computer, and the same
data used again later.

**You need:** a released version ([First dataset and run](first-run.md)).
Role `dev`, `ops` or `admin`.

## 1. Submit on the version

Console → **Pipelines** → your app → **Run**. Set:

- `experiment-name`: `cats-baseline`
- `dataset`: `dataset-cats@v1`

and **Submit**. Note the run name the run page shows, for example `my-app-pipeline-x7k2p`.

## 2. Find the result

When every step is green: console → **Pipelines** → your app → **Outputs**, or lakeFS →
`outputs-<app>` → `main` → `checkpoints/cats-baseline/my-app-pipeline-x7k2p/`.

**You should see** one commit per step that wrote results. Open a commit: its details name the
dataset (`dataset_ref`) and the exact commit it read (`dataset_commit`).

```bash
kaosctl dataset pull outputs-<app>@main ./results --prefix checkpoints/cats-baseline/my-app-pipeline-x7k2p/
```

## 3. Use the same data again

`v1` is a tag and never changes, so a new run on `dataset-cats@v1` reads the same data. To be exact
even for a run that read `latest`, use the commit from the result:

```bash
kaosctl dataset pull dataset-cats@<dataset_commit> ./cats-as-trained
```

If the step recorded a data lock in MLflow, `kaosctl run --lock <mlflow-run-id> -- <command>` replays
every read ([Results](results.md#replay-a-runs-data)).

## A trained model instead

With the yolo template the same run trains a model. Its weights land in the same place, and MLflow
links them: see [Results and weights](cookbook/8-results-and-weights.md) and the yolo guide's
[run small, then full](https://github.com/novelcore/yolo-pipelines-template/blob/dev/docs/run-small-and-full.md).
