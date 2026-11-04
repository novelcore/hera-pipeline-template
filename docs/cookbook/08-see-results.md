# 8. See the results, metrics and weights

## What gets recorded

- **MLflow** records each run's settings, metrics, charts and registered models.
- **lakeFS** keeps the files a run saves, such as weights, in a repository called `outputs-<your pipeline>`.

## Do this

**Record metrics.** In your training step, once per run:

```python
from kaos_lib.mlflow import mlflow
mlflow()                        # connects to your project's MLflow, no password needed
import mlflow as mlf
mlf.set_experiment(cfg["experiment"]["name"])
with mlf.start_run():
    mlf.log_param("dataset", cfg["dataset"])
    mlf.log_metric("accuracy", 0.87)
```

This needs the `mlflow` extra: use `kaos-lib[mlflow]==0.4.0rc10` in the Dockerfile instead of `[zitadel]`.

**Save weights.**

```python
import os
from kaos_lib import outputs

with outputs.run(os.environ["CHECKPOINT_BUCKET"], cfg["experiment"]["name"], os.environ["KUBECORE_RUN_ID"]) as r:
    r.save("./weights")                      # keeps them, even if the step is retried
    r.finish({"dataset_ref": cfg["dataset"]})  # publishes them in one commit
```

**Look at them.**

1. Open MLflow from the console (your pipeline's page links to it; if you cannot find the link, ask your project administrator). Find your run by the experiment name you set. Open it for its parameters, metrics and artifacts.
2. To **compare runs**, tick two or more runs in MLflow's run list and click its **Compare** button.
3. For weights: open **Open in lakeFS** from a page in the console, then open the repository `outputs-<your pipeline>`. Files are under `checkpoints/<experiment>/<run>/`.

## You should now see

- Your run in MLflow with the dataset version in its parameters, so you know which data produced it.
- Your weight files in lakeFS, in one commit per step of the run.
- The two runs side by side in the compare view.

Next: [share a dataset with another project](09-share-a-dataset.md).
