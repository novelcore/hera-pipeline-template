# hera-pipeline-template

**hera** is the starter ("scaffold") template for ML pipelines on KAOS. You write the pipeline in **Python** ([Hera](https://github.com/argoproj-labs/hera)), keep its settings in a **[Hydra](https://github.com/facebookresearch/hydra) config tree**, and push. KAOS builds your steps and gives you a run form. You never touch servers. For object detection there is a ready-made template built on hera: [yolo](https://github.com/novelcore/yolo-pipelines-template).

## Start here

You were given a KAOS account and a project? Follow the **[cookbook](docs/index.md)**: sign in, create a dataset, create a pipeline from this template in the console, run it, read the results.

The same guide is published at <https://novelcore.github.io/hera-pipeline-template/>. That site shows the **released** version, so a page that is new here may not be there yet.

The 5-minute path:

1. Sign in to the KAOS console; **Machine learning** is in the sidebar.
2. `pip install` kaos-lib and `kaosctl login` ([how](docs/cookbook/03-install-kaosctl.md)).
3. `kaosctl dataset create <name> --layout yolo`, upload data, `kaosctl dataset release dataset-<name>` ([how](docs/cookbook/04-create-a-dataset.md)).
4. **Pipelines, New pipeline**, choose the hera template ([how](docs/cookbook/05-create-your-pipeline.md)).
5. Open its run form, pick `dataset-<name>@v1`, Submit ([how](docs/cookbook/07-run-it.md)).

Library docs (datasets, outputs, MLflow, `kaosctl`): [kaos-lib documentation](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html).

## Why this exists

The whole DAG is **one small `pipeline.py`** and a tree of small YAML files. This
template ships a single example step (`hello-world`) so you have a working
pipeline from the first push — replace it with your own steps.

```python
# pipeline.py — the ENTIRE pipeline definition
from kubecore.authoring import pipeline, step

with pipeline("ml-pipeline") as p:  # KAOS names it after your pipeline when it releases
    hello = step("hello-world", reads=["experiment"])
```

Add more steps and wire dependencies as your pipeline grows:

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
steps/<name>/          your step code + Dockerfile (one dir per step)
kubecore/              helper code that ships with the template — do not edit
                       (not the old `kubecore` Python package; that is now kaos-lib)
pyproject.toml         PEP 621, pinned render deps
```

## Two core moves (full guide: [DEVELOPER.md](DEVELOPER.md))

- **Add a parameter** → add a leaf to `config/…`. Push. The form has it.
- **Add a step** → `mkdir steps/<name>` + a Dockerfile + an entry that reads its
  config slice, then one `step("<name>", reads=[…], needs=[…])` line in
  `pipeline.py`. Push.

## Local iteration (no cluster)

```bash
./run.sh                                       # venv + render + enhance + compose
python -m kubecore.compose experiment.name=demo   # try config overrides locally
```

`out/params.yaml` is exactly what your steps receive at run time; a typo or a
bad `reads=` fails locally with the same message the cluster gives you.

## What the platform does for you (you never write this)

Building your step images, access to tracking and storage,
per-step machine-class selection from your project's classes,
per-run sizing knobs, `/dev/shm`, release, and the run form —
all added for you at release time. Your `pipeline.py` stays pure structure.

**Adding your first step?** Start with **[ADD-A-STEP.md](ADD-A-STEP.md)** — a
complete copy-paste walkthrough for newcomers (every command, every gotcha).

See **[DEVELOPER.md](DEVELOPER.md)** for the complete operating manual.

## Running steps on a supercomputer, Slurm (MeluXina)

When your project has a Slurm (MeluXina) environment, every step's `{step}-class` dropdown on the
run form also offers its classes:

| class | what it is | typical use |
|---|---|---|
| `meluxina-gpu` | 4× A100-40GB, 2× EPYC 7452, 512 GB | GPU-heavy steps |
| `meluxina-cpu` | 2× EPYC 7452 (128 cores), 512 GB | heavy CPU steps |
| `meluxina-largemem` | 4 TB RAM | data that does not fit a node |

Pick one for a step and only that step runs as a Slurm job on MeluXina; every other
step keeps its in-cluster class. Nothing in this repository changes: the platform
pulls the step image into an Apptainer SIF, runs the same command the pod would run,
and brings the step's declared outputs back so the next step consumes them as usual.

- Queue time is real (minutes to hours) — the pipeline waits; the `pipeline-info`
  field on the form lists the classes and the account.
- Give long steps a wall-clock limit in `pipeline.py`: `step(..., hpc_time_limit="12h")`
  (default 4 h). See [DEVELOPER.md §8.1](DEVELOPER.md).
- Steps pinned with a `compute-class` annotation stay in-cluster.

## Checking the docs

Before you push doc changes run `make docs-check` (or `scripts/check-docs.sh`). It builds the site with `mkdocs build --strict` and checks every internal link and anchor; `scripts/check-docs.sh --external` also checks external links.

## License

This project is licensed under the Apache License, Version 2.0. See the
[LICENSE](LICENSE) file for the full terms.
