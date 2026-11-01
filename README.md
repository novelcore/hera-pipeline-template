# hera-pipeline-template

A pipeline you author in **Python** ([Hera](https://github.com/argoproj-labs/hera))
with parameters in a **[Hydra](https://github.com/facebookresearch/hydra) config tree**.
Clone it, add your steps and parameters, push — the platform builds your images
and releases a runnable pipeline. You never touch Kubernetes.

This template is the source new pipeline apps are seeded from.

## Contents

- [The pipeline in one file](#the-pipeline-in-one-file)
- [Datasets](#datasets)
- [Results](#results)
- [The `kubecore` package](#the-kubecore-package)
- [Running on MeluXina](#running-on-meluxina)
- [Local iteration](#local-iteration-no-cluster)
- [Where to read next](#where-to-read-next)

## The pipeline in one file

The whole DAG is **one small `pipeline.py`** and a tree of small YAML files. The
template ships two example steps so you have a working pipeline from the first
push — replace them with your own.

```python
# pipeline.py — the ENTIRE pipeline definition
from kubecore.authoring import pipeline, step

with pipeline("ml-pipeline") as p:  # platform renames to {app}-pipeline at release
    load  = step("dataset-loading", reads=["dataset"], outputs=["dataset-info"])
    hello = step("hello-world", reads=["experiment", "dataset"], needs=[load])
```

`dataset-loading` pins the dataset the run picked; `hello-world` reads it and writes a
result. Add more steps and wire dependencies as your pipeline grows:

```python
with pipeline("ml-pipeline") as p:
    prep  = step("prepare", reads=["experiment"], outputs=["prepared"])
    run   = step("run", gpu=True, needs=[prep], reads=["experiment", "train"],
                 outputs=["result"])
    report = step("report", needs=[run], reads=["experiment"])
```

**One rule: the `config/` tree IS the submit form.** Every scalar in `config/`
becomes a form field; every group directory becomes a dropdown. Add a leaf → a
field appears. No parameter wiring anywhere.

## Layout

```
pipeline.py            the DAG (steps, reads=, gpu=, needs=, when=)
config/                THE config tree — all your parameters
  config.yaml            the defaults list (which group options are default)
  experiment.yaml        a section of scalar leaves (add your own files/groups)
  dataset.yaml           the `dataset` field: <dataset-repo>@<version>
steps/<name>/          your step code + Dockerfile (one dir per step)
kubecore/              platform-owned engine — SEEDED, DO NOT EDIT
packages/kubecore/     the kubecore Python PACKAGE: datasets, run outputs, the `kubecore` command
tests/, step_tests/    engine tests; step-code tests (two commands, see DEVELOPER.md §12)
docs/                  the guides (see "Where to read next")
pyproject.toml         PEP 621, pinned render deps
```

## Two core moves (full guide: [DEVELOPER.md](DEVELOPER.md))

- **Add a parameter** → add a leaf to `config/…`. Push. The form has it.
- **Add a step** → `mkdir steps/<name>` + a Dockerfile + an entry that reads its
  config slice, then one `step("<name>", reads=[…], needs=[…])` line in
  `pipeline.py`. Push.

## Datasets

A **dataset is a lakeFS repository** named `dataset-<name>`. Your project starts with
one, `dataset-default`.

- **Versions** are tags on `main`: `v1`, `v2`, … `latest` means the head of `main`. A run
  never reads "whatever is there now": it picks one version, and every step of that run
  reads exactly that commit.
- **Changes** reach `main` through a **pull request**. After a pull request is merged,
  `kubecore dataset release` tags the next version.
- **Pick it in the pipeline.** The run form has a `dataset` field, a dropdown of
  `<dataset-repo>@<version>` choices, newest first (`dataset-cats@v2`, `dataset-cats@v1`,
  `dataset-cats@latest`, …). The default is `dataset-default`'s newest version. The list
  is refreshed when a dataset or a version changes. The field comes from
  `config/dataset.yaml`; keep a field named exactly `dataset` in your pipeline.
- **Templates are optional.** `kubecore dataset create` can start a repository from a
  format template (the starter layout, for example `ultralytics`), but you do not need
  one: any repository named `dataset-<something>` that you create by hand in lakeFS
  becomes a dataset after its first commit. Any repository can also be read from code:
  `datasets.materialize("<repo>@<ref>")` (see the package section).
- A pipeline **never writes to a dataset**.

Step by step, with every command: [first dataset → first run → your results](docs/first-run.md).
Concepts and the commands in one place: [docs/datasets.md](docs/datasets.md).

## Results

Each app has its own repository, **`outputs-<app>`**, made by the platform. A step
writes there with the package's **run writer**:

- everything a step saves is committed on its own branch `run-<run>-<kind>` as it is saved,
  so it survives a lost pod;
- `finish()` merges the branch into `main`: **one merge commit per step per run**, under
  `<kind>/<experiment>/<run>/` (`checkpoints/…` by default), and deletes the branch. The
  commit records the app, experiment, run, and whatever you pass (dataset, MLflow run);
- a retried step finds the branch and **resumes**: `r.latest("last.pt")` gives back the
  newest checkpoint it already saved.

```python
from kubecore import outputs
with outputs.run("my-app", experiment, run_id) as r:
    resume = r.latest("last.pt")                 # None on a first attempt
    ...                                          # train; on every checkpoint:
    r.save("./last.pt")                          # committed on the run branch
    r.finish({"dataset_ref": "dataset-cats@v2"}) # one merge commit on main
```

Writing a step that reads a dataset and writes results: [docs/write-a-step.md](docs/write-a-step.md).

## The `kubecore` package

`packages/kubecore/` is the Python package behind all of this. Install it on your
computer inside a virtual environment, from this repository, at the commit your step
images use (`KUBECORE_PKG_COMMIT` in `steps/*/Dockerfile`):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install "git+https://github.com/novelcore/hera-pipeline-template@<commit>#subdirectory=packages/kubecore"
kubecore login                    # opens your browser once
```

Run the commands inside your app folder: it carries the file that tells the tool where
your project's lakeFS is.

| command | what it does |
|---|---|
| `kubecore dataset create <name> [--classes a,b] [--template ultralytics]` | a new `dataset-<name>` with a starter layout |
| `kubecore dataset pull <repo>@<ref> [dir]` | download a version to work on |
| `kubecore dataset validate <dir>` | check a folder against the dataset's format |
| `kubecore dataset push <dir> <repo> -m "message"` | validate, upload to a draft, open a pull request |
| `kubecore dataset release <repo>` | tag the head of `main` as the next version |
| `kubecore dataset list` / `versions <repo>` | what exists |

From code (a step, a notebook):

```python
from kubecore import datasets
entry = datasets.materialize("dataset-cats@v2")   # local files; a data.yaml for an ultralytics dataset
```

`materialize` downloads once and reuses the copy; on MeluXina it uses the copy the
platform already staged.

## Running on MeluXina

When the project's pool is HPC-enabled, every step's `{step}-class` dropdown on the
Argo submit form also offers the MeluXina classes:

| class | what it is | typical use |
|---|---|---|
| `meluxina-gpu` | 4× A100-40GB, 2× EPYC 7452, 512 GB | GPU-heavy steps |
| `meluxina-cpu` | 2× EPYC 7452 (128 cores), 512 GB | heavy CPU steps |
| `meluxina-largemem` | 4 TB RAM | data that does not fit a node |

Pick one for a step and only that step runs as a Slurm job on MeluXina; every other
step keeps its in-cluster class. Nothing in this repository changes:

- **The dataset is staged** on MeluXina before the job starts (once per version; a new
  version copies only what changed), and your step reads it through the same
  `datasets.materialize(...)` call.
- **The step runs your image** and writes its results with the same run writer, so
  checkpoints and the merge commit appear in `outputs-<app>` exactly as for an
  in-cluster step; declared step outputs come back so the next step consumes them as usual.
- Queue time is real (minutes to hours) — the pipeline waits; the `pipeline-info`
  field on the form lists the classes and the account.
- Give long steps a wall-clock limit in `pipeline.py`: `step(..., hpc_time_limit="12h")`
  (default 4 h). See [DEVELOPER.md §8.1](DEVELOPER.md).
- Steps pinned with a `compute-class` annotation stay in-cluster.

## Local iteration (no cluster)

```bash
./run.sh                                       # venv + render + enhance + compose
python -m kubecore.compose experiment.name=demo   # try config overrides locally
```

`out/params.yaml` is exactly what your steps receive at run time; a typo or a
bad `reads=` fails locally with the same message the cluster gives you.

## What the platform does for you (you never write this)

Image supply-chain (container registry), tracking/artifact-store env + secrets,
per-step compute-class selection + node scheduling from your pool's classes,
per-run sizing knobs, `/dev/shm`, GitOps release, and the Argo submit form —
all injected at release time. Your `pipeline.py` stays pure structure.

## Where to read next

| you want to | read |
|---|---|
| make your first dataset, run on it, find the results | [docs/first-run.md](docs/first-run.md) |
| understand datasets, versions, templates and the commands | [docs/datasets.md](docs/datasets.md) |
| write a step that reads a dataset and writes results | [docs/write-a-step.md](docs/write-a-step.md) |
| add your first step | [ADD-A-STEP.md](ADD-A-STEP.md) |
| the complete operating manual (config, tests, HPC) | [DEVELOPER.md](DEVELOPER.md) |
| how the platform works internally | [MECHANISMS.md](MECHANISMS.md) |

## License

This project is licensed under the Apache License, Version 2.0. See the
[LICENSE](LICENSE) file for the full terms.
