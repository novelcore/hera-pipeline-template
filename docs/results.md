# Results

Where a run's results go and how to find them. [Chapter 8](cookbook/8-results-and-weights.md) walks through
it; this page is the short reference for this template. What a step hands on, and what a run records about the
data it read and wrote, is explained once for every pipeline in [Results](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/results.html) of the kaos-lib guide.

## What the template's pipeline writes

| step | declares | where it lands |
|---|---|---|
| `prepare` | `produces=[dataset("clean")]` | a new version of the dataset `dataset-<your app>-clean` |
| `hello-world` | `produces=[artifact("report")]` | `outputs-<app>`, under `report/<experiment>/<run>/hello.txt` |

Each step also hands on a few small values with `step.result(...)`: `prepare` hands on `files` and `dropped`,
`hello-world` hands on `files`. They are shown on the run page.

## The outputs repository

Each ML app has one repository, **`outputs-<app>`**, which the platform creates with the app. Models and
artifacts of every run are kept there:

```
outputs-<app>
└── main
    └── <name>/<experiment>/<run>/     <name> is the name in model("<name>") or artifact("<name>")
```

- One commit on `main` per output per run.
- Nobody writes to `main` by hand. Results only come from runs.

Find and download them:

```bash
kaosctl dataset pull outputs-<app>@main ./results --prefix report/<experiment>/<run>/
```

or console → **Pipelines** → your app → **Outputs**.

## The dataset the pipeline produces

`dataset-<your app>-clean` is a dataset like any other: it is listed with your project's datasets and you pull it with
`kaosctl dataset pull dataset-<your app>-clean ./clean`. Every run of the pipeline writes one version of it. `latest` moves
to a run's version only when the run asks for it on the run form
([A dataset a step produces](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/steps-and-datasets.html#a-dataset-a-step-produces)).

## Log to MLflow from a step

`kaos_lib.mlflow.mlflow()` signs the step in to your project's MLflow. What the step read and wrote is recorded
on its MLflow run for you ([MLflow](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/mlflow.html)).

## Run again on the data of a past run

[Data lock](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/data-lock.html) shows how to run a command on exactly the dataset versions a past run read.

## Models

The yolo template logs a model per training run and registers it. See its
[results](https://novelcore.github.io/yolo-pipelines-template/results/) and
[promote](https://novelcore.github.io/yolo-pipelines-template/promote/) pages. The console's
**Models** page lists every registered model of a project, with **Open in MLflow**.
