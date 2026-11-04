# Write results from a step

**Goal:** a step that writes its results to your app's outputs repository, saves progress as it
goes, and continues where it stopped when it is retried.

**You need:** a step that installs kaos-lib ([Use a dataset in a step](dataset-in-a-step.md),
part 2). The template's `steps/hello_world/` writes a result this way; copy it.

## 1. Write results

```python
import os
from kaos_lib import outputs

app = os.environ["CHECKPOINT_BUCKET"]        # outputs-<app>, set by the platform
run = os.environ["KUBECORE_RUN_ID"]          # the Argo run name

with outputs.run(app, experiment, run) as r:
    r.save("./results")                      # a folder or files
    commit = r.finish({"dataset_ref": info["dataset"], "dataset_commit": info["dataset_commit"]})
```

The files land in `outputs-<app>` under `checkpoints/<experiment>/<run>/`, in **one merge commit
on `main`**. The commit's details carry what you passed to `finish`. For another top folder, pass
the kind: `outputs.run(app, experiment, run, "reports")` writes under `reports/<experiment>/<run>/`.

A step never writes to a dataset. Results always go to `outputs-<app>`.

## 2. Save progress and resume

For a long step, save as you go. Every `save` is committed on the run's own branch,
`run-<run>-<kind>`, so it survives a lost pod. `finish` merges once, at the end.

```python
with outputs.run(app, experiment, run) as r:
    resume = r.latest("last.pt")             # a local path, or None on a first attempt
    state = load(resume) if resume else fresh_state()
    for epoch in range(state.epoch, epochs):
        train_one_epoch(state)
        if epoch % 10 == 0:
            torch.save(state, "last.pt")
            r.save("last.pt")                # durable now
    r.finish({"dataset_ref": info["dataset"]})
```

- An exception inside the `with` block neither merges nor deletes the branch. **Retry** in Argo
  reruns the step under the same run name, and `latest` finds what it saved.
- **Resubmit** is a new run with a new name, so it starts fresh.
- Saving identical content again, and finishing twice, are not errors.

## 3. Link the result to MLflow

Pass the MLflow run id to `finish`, and tag the MLflow run with where the files are. Then each side
names the other ([Results](results.md#log-to-mlflow-from-a-step)).

## 4. On MeluXina

Nothing changes in your code. When a person picks a `meluxina-*` class for the step, the step
writes with the same run writer, and the commit appears in `outputs-<app>` as for a step on your project's own machines ([MeluXina](meluxina.md)).

## 5. Test it on your laptop

Step code that imports `kaos_lib` has its own test command, separate from the engine tests: see
`step_tests/README.md` and DEVELOPER.md §15. The step tests use kaos-lib's in-memory lakeFS, vendored
as `step_tests/fake_lakefs.py`.

**Next:** [Results](results.md).
