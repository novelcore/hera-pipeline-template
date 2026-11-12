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
`outputs-<app>` → `main` → `report/cats-baseline/my-app-pipeline-x7k2p/`.

**You should see** `hello.txt`, and one commit for it on `main`. The exact version of every dataset a step
read is in the step's result, on the run page: `reads`, with the dataset and its `commit`.

```bash
kaosctl dataset pull outputs-<app>@main ./results --prefix report/cats-baseline/my-app-pipeline-x7k2p/
```

## 3. Use the same data again

`v1` is a tag and never changes, so a new run on `dataset-cats@v1` reads the same data. To be exact
even for a run that read the newest version, use the commit from the step's result:

```bash
kaosctl dataset pull dataset-cats@<commit> ./cats-as-trained
```

For a step that logs to MLflow, `kaosctl run --lock <mlflow-run-id> -- <command>` replays
every read ([Data lock](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/data-lock.html)).

## A trained model instead

With the yolo template the same run trains a model. Its weights land in the same place, and MLflow
links them: see [Results and weights](cookbook/8-results-and-weights.md) and the yolo guide's
[run small, then full](https://github.com/novelcore/yolo-pipelines-template/blob/dev/docs/run-small-and-full.md).
