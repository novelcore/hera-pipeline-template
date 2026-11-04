# Results

Where a run's results go, how to find them, and how they link to MLflow and to the data they came
from. [Chapter 8](cookbook/8-results-and-weights.md) walks through it; this page is the reference.

## The outputs repository

Each ML app has one lakeFS repository, **`outputs-<app>`**, which the platform creates with the app.

```
outputs-<app>
└── main
    ├── checkpoints/<experiment>/<run>/     default kind
    └── <kind>/<experiment>/<run>/          e.g. quantization/, reports/
```

- One **merge commit on `main`** per step per run. The commit is titled `<kind>: <experiment>/<run>`
  and its details record the app, the experiment, the run, the kind, and what the step passed to
  `finish()`.
- While a step runs, its saves are on the branch `run-<run>-<kind>`. `finish()` merges the branch
  and deletes it. A failed step leaves the branch for its retry.
- Nobody writes to `main` by hand. Results only come from runs.

Find and download them:

```bash
kaosctl dataset pull outputs-<app>@main ./results --prefix checkpoints/<experiment>/<run>/
```

or console → **Pipelines** → your app → **Outputs**, or lakeFS → `outputs-<app>`.

## Log to MLflow from a step

The platform gives each step its project's MLflow address and sign-in (`MLFLOW_TRACKING_URI`, and a
machine key). `kaos_lib.mlflow.mlflow()` points the `mlflow` module at it and adds the token. Install
MLflow in the step image next to kaos-lib. The platform replaces the kaos-lib requirement, so add
the `mlflow` extra's packages yourself:

```dockerfile
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}" "mlflow-skinny>=3,<4" PyJWT cryptography
```

```python
import os
import mlflow as mlf
from importlib.metadata import version
from kaos_lib import lock, outputs
from kaos_lib.mlflow import mlflow

mlflow()                                             # tracking address + sign-in from the environment
mlf.set_experiment(experiment)
with mlf.start_run(run_name=os.environ["KUBECORE_RUN_ID"]) as run:
    mlf.log_params({"epochs": epochs, "dataset": info["dataset"], "dataset_commit": info["dataset_commit"]})
    mlf.set_tag("kaos_lib.version", version("kaos-lib"))
    ...                                              # train; mlf.log_metric("loss", loss, step=epoch)
    with outputs.run(app, experiment, os.environ["KUBECORE_RUN_ID"]) as r:
        r.save("./weights")
        commit = r.finish({"dataset_ref": info["dataset"], "mlflow_run_id": run.info.run_id})
    mlf.set_tags({"kaos.outputs_repo": r.repo, "kaos.outputs_commit": commit,
                  "kaos.outputs_path": r.prefix, "kaos.workflow": os.environ["KUBECORE_RUN_ID"]})
    lock.write(run.info.run_id)                      # the data lock: every dataset commit this step read
```

## What a run records

| where | what | written by |
|---|---|---|
| lakeFS commit details | `app`, `experiment`, `run`, `kind`, plus what the step passes (`dataset_ref`, `dataset_commit`, `mlflow_run_id`) | `outputs.run(...).finish()` |
| MLflow tag `kaos_lib.version` | the kaos-lib the step ran | the step |
| MLflow tags `kaos_lib.data.<repo>.commit` (and `.owner` for a shared dataset) | each dataset commit read | `lock.write` |
| MLflow artifact `data.lock.json` | `{"version": 1, "reads": [{"repo", "owner", "ref", "commit"}]}` | `lock.write` |
| MLflow tags `kaos.outputs_repo`, `kaos.outputs_commit`, `kaos.outputs_path`, `kaos.workflow` | where the files are | the step (yolo's training step does it) |

## Replay a run's data

```bash
export MLFLOW_TRACKING_URI=<the address behind the console's MLflow link>
kaosctl run --lock <mlflow-run-id> -- python evaluate.py
```

The command runs with `$KAOS_LIB_LOCK` set to the run's lock. Every dataset read inside it returns
the locked commit. In Python, `lock.load(run_id)` reads a lock back and `DataLock.replay(lock)` applies
it in the current process.

## Models

The yolo template logs a model per training run, registers it, and tags the matching lakeFS commit
`model-<name>-v<version>`. See its [results](https://novelcore.github.io/yolo-pipelines-template/results/)
and [promote](https://novelcore.github.io/yolo-pipelines-template/promote/) pages. The console's
**Models** page lists every registered model of a project, with **Open in MLflow**.
