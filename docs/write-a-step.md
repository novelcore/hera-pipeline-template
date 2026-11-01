# Write a step that uses a dataset

A step that trains or analyses data does three things with the `kubecore` package: reads the
dataset the run pinned, writes its results, and (for long steps) saves progress so a retry
resumes. The template's `steps/hello_world/` is a working example; this page explains it.

## 1. Wire it in `pipeline.py`

```python
load  = step("dataset-loading", reads=["dataset"], outputs=["dataset-info"])
mine  = step("my-step", reads=["experiment", "dataset"], needs=[load])
```

`dataset-loading` resolves the run's `dataset` pick to a commit and outputs
`dataset-info`: `{dataset, dataset_repo, dataset_version, dataset_commit}`. A step that
`needs=[load]` receives it as `--dataset-info`. Always use the commit from there, never the
pick itself: `latest` can move during a run.

## 2. Install the package in the step image

In `steps/my_step/Dockerfile`, copy the lines from `steps/hello_world/Dockerfile`:

```dockerfile
ARG KUBECORE_PKG_COMMIT=<the commit used by the template>
RUN pip install --no-cache-dir \
    "https://github.com/novelcore/hera-pipeline-template/archive/${KUBECORE_PKG_COMMIT}.zip#subdirectory=packages/kubecore"
COPY app/ ./app/
```

Copy only `app/`. Do not copy the template's `kubecore/` folder into a step image: it is the
platform's engine, it has the same import name as the package, and the two must never be on
the same path.

## 3. Read the dataset

```python
import argparse, json
from kubecore import datasets

parser = argparse.ArgumentParser()
parser.add_argument("--params", required=True)
parser.add_argument("--dataset-info", default="{}")
args, _ = parser.parse_known_args()
info = json.loads(args.dataset_info)

ref = datasets.DatasetRef.parse(info["dataset"]).with_commit(info["dataset_commit"])
entry = datasets.materialize(ref)       # ultralytics: the data.yaml path; no label: a folder
```

`with_commit` makes the call read exactly the commit `dataset-loading` pinned. The format
comes from the repository's label. The credentials and the lakeFS address come from the step's
environment: you write none of that.

## 4. Write results

```python
import os
from kubecore import outputs

app = os.environ["CHECKPOINT_BUCKET"]        # outputs-<app>, set by the platform
run = os.environ["KUBECORE_RUN_ID"]          # the Argo run name

with outputs.run(app, experiment, run) as r:
    r.save("./results")                      # a folder or files, committed on the run branch
    r.finish({"dataset_ref": info["dataset"], "dataset_commit": info["dataset_commit"]})
```

The files end up in `outputs-<app>` under `checkpoints/<experiment>/<run>/`, in **one merge
commit on `main`** whose details carry what you passed to `finish`. Use `kind=` for another top
folder: `outputs.run(app, experiment, run, "reports")`.

## 5. Save progress and resume

For a long step, save as you go. Every `save` is committed on the run's own branch
`run-<run>-<kind>`, so it survives a lost pod or a retry. `finish` merges once, at the end.

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

- An exception inside the `with` block neither merges nor deletes the branch, so the retry
  continues from it.
- Saving identical content again, and finishing twice, are not errors.

## 6. MeluXina

Nothing changes in your code. Choose a `meluxina-*` class for the step on the submit form: the
platform stages the dataset commit before the job starts, `materialize` finds it, and the step
writes its results with the same run writer.

## 7. Test it without a cluster

Step code that imports `kubecore` runs in its own test command, apart from the engine tests,
because of the shared import name: see `step_tests/README.md` and DEVELOPER.md §15. The package
ships an in-memory lakeFS (`packages/kubecore/tests/fake_lakefs.py`) that the template's step tests
use.
