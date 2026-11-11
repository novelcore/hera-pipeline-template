# 8. Results and weights

**Goal:** you find what your runs wrote, see their MLflow runs, compare two runs and their weights,
and can replay a run on exactly the data it read.

**Who can do it:** anyone on a project team can read outputs. In MLflow, a project `admin` can
register and promote models by hand. For the other roles, verify the rights on your project
([chapter 1](1-youre-in.md)). Pipelines register models with the project's own MLflow account, so
`registration-promote_to` on the yolo form works whoever submits.

## Where outputs land

Every app has its own lakeFS repository, **`outputs-<app>`**. Each step that writes results adds
**one merge commit to `main` per run**, under:

```
outputs-<app>/main/checkpoints/<experiment>/<run>/
```

`<experiment>` is the run's `experiment-name` field. `<run>` is the run's name, for example
`my-app-pipeline-x7k2p`. A step can choose a different top folder from `checkpoints/`, as yolo does
with `quantization/`. The commit's details record the app, experiment, run and kind, plus what the
step passed in (the dataset and its commit, the MLflow run id).

**Find them:** console → **Pipelines** → your app → **Outputs**, or lakeFS → `outputs-<app>` →
branch `main` → `checkpoints/`. **Download them:**

```bash
kaosctl dataset pull outputs-<app>@main ./results --prefix checkpoints/<experiment>/<run>/
```

For the shipped pipeline you find `hello.json`, which names the dataset and the commit it read.

## MLflow runs

A step that logs to MLflow puts there the run's **metrics**, its **parameters** (every form field
it used), the **dataset commit** it read, and the **`kaos_lib.*` tags**. The yolo template's
training step does all of this. In your own step, call `kaos_lib.mlflow.mlflow()` once: KAOS
sets the step's tracking address and sign-in, and kaos-lib adds the token
([Results](../results.md#log-to-mlflow-from-a-step) has the snippet).

Open MLflow from the console (**Pipelines** → your app → **MLflow**) → **Experiments** → your
experiment. Each run shows:

| where | what |
|---|---|
| **Parameters** | the settings of the run, and the dataset repository, version and commit |
| **Metrics** | the numbers, with their curves over the epochs |
| **Tags** | `kaos_lib.version`; `kaos_lib.data.<repo>.commit` (each dataset commit it read); `kaos.outputs_repo`, `kaos.outputs_commit`, `kaos.outputs_path` (where its files are in lakeFS); `kaos.workflow` (the run's name) |
| **Artifacts** | plots, sample predictions, and `data.lock.json` (the data lock) |

## The model is linked both ways

- **From MLflow to lakeFS:** the run's (or model's) tags `kaos.outputs_repo`, `kaos.outputs_commit`
  and `kaos.outputs_path` name the repository, the commit and the folder of the weights.
- **From lakeFS to MLflow:** the commit's details carry `mlflow_run_id`.

The weights themselves stay in lakeFS. MLflow holds the numbers and the links.

## Compare runs and weights

1. **Compare in MLflow:** in the experiment, tick two or more runs and click **Compare**. You see
   their parameters side by side, which differ, and their metric curves on one chart.
2. **Compare models:** an experiment's **Models** tab lists each run's logged model with its final
   scores. A **registered model** (*Models* in the top bar) keeps the versions you chose, with
   aliases such as `champion` ([yolo: promote a model](https://novelcore.github.io/yolo-pipelines-template/promote/)).
3. **Download two runs' weights and evaluate them yourself:**

    ```bash
    kaosctl dataset pull outputs-<app>@main ./run-a --prefix checkpoints/<experiment>/<run-a>/
    kaosctl dataset pull outputs-<app>@main ./run-b --prefix checkpoints/<experiment>/<run-b>/
    python evaluate.py ./run-a/best.pt ./run-b/best.pt --data ./dataset-cats/data.yaml
    ```

    `evaluate.py` is your own evaluation script. The console's **Models** page lists the registered
    models of the project, with **Open in MLflow**.

## Replay a run's exact data

A step that calls `kaos_lib.lock.write(<mlflow run id>)` records every dataset commit it read in
`data.lock.json` on the MLflow run. To run any command on exactly that data, for example a local
evaluation or a re-training:

```bash
export MLFLOW_TRACKING_URI=<the address behind the console's MLflow link>
kaosctl run --lock <mlflow-run-id> -- python evaluate.py ./run-a/best.pt
```

`kaosctl` prints the locked reads (`dataset-cats@v1 -> <commit>`). Every
`datasets.materialize`/`resolve` inside the command then returns those commits, even if `v1` was
re-tagged or `latest` has moved on. This needs the `mlflow` extra
([chapter 4](4-install-kaosctl.md)).

## If it isn't there

| symptom | fix |
|---|---|
| nothing under `checkpoints/` | the step did not reach `finish()`; a failed step merges nothing. Its saves are on the branch `run-<run>-checkpoints` until a retry finishes |
| no MLflow run | your step does not log to MLflow; add it ([Results](../results.md#log-to-mlflow-from-a-step)) |
| MLflow says `401` from your laptop | sign in again with `kaosctl login` **inside the app folder** |
| `kaosctl run --lock`: no data lock on the run | that run's step never called `lock.write` |

**Next:** [9. The yolo use case](9-the-yolo-use-case.md).
