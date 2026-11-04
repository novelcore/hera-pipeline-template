# kaos_pipeline/ — the pipeline engine (platform-owned, do not edit in an app repo)

This folder ships with the template and is **replaced wholesale by the platform on upgrade**:
edits here are lost. It is the code that turns your `pipeline.py` + `config/` tree into the
released pipeline and the run form. You never change it; this page explains what it does so
you can read it when something surprises you.

> The folder is called `kaos_pipeline`, not `platform`, on purpose: a top-level `platform`
> package shadows Python's standard-library `platform` module and breaks any dependency that
> calls `platform.system()`. (`kaos` alone would clash with nothing; `kaos_pipeline` is the
> chosen name.) Pipelines created before the rename may still have this folder as `kubecore/`;
> it works the same.

## The four modules

| Module | When it runs | Job |
|---|---|---|
| `authoring.py` | when your `pipeline.py` is rendered | `step()` / `pipeline()` build the plain Hera containers and the DAG; adds the compose-and-validate step as task 1; `gpu=True` requests one GPU |
| `derive_tree.py` | when your `pipeline.py` is rendered | composes the Hydra `config/` tree and derives the run-form fields (group to dropdown, plain value to field, dots to dashes); runs the `reads=` check |
| `enhance.py` | after render, on the platform side | post-processes the rendered pipeline: app-scoped name, step images, environment variables, scheduling, per-step sizing and class dropdowns. Plain dicts, no Hera dependency |
| `compose.py` | at run time, in the first step's container | `python -m kaos_pipeline.compose` composes the tree and the submitted values into the single resolved `params.yaml`, validates it, and fails fast before any GPU is used |

`authoring` and `derive_tree` are imported by your `pipeline.py`. `compose` runs as a program
in the compose step's image. `enhance` runs on the platform side and is never importable from
your code: `pipeline.py` is rendered without any credentials, and the enhancer runs separately.
`meluxina.py`, `outputs_repo.py` and `kaos_lib_support.py` are helpers of `enhance.py` (the HPC
(Slurm) leg, the results location and the kaos-lib version window).

## What the engine enforces

- **The pipeline's name is forced to `{app}-pipeline`**, whatever `pipeline.py` wrote, so two
  apps never collide.
- **Step images are always rewritten** to the image the platform built for that step, unless
  the step carries the `platform.kubecore.io/image` annotation naming a ready-made image.
- **A step is a GPU step iff it requests a GPU** (`gpu=True`). The enhancer sends it to a GPU
  class. No annotation is needed.
- **`reads=` check**: the release fails if a step declares a config section that is not in the
  composed tree. For sections with a typed schema (`data`, `quantization`) a real file must also
  contribute the key, because the schema's defaults would otherwise hide a rename.
- **Only-fill-absent**: a node selector, environment variable or resource you set yourself wins;
  the platform fills only what is missing.
- **Environment variables** the enhancer sets on every step: `KAOS_RUN_ID` and
  `KAOS_WORKFLOW_NAME` (the run's name), plus the deprecated aliases `KUBECORE_RUN_ID` and
  `KUBECORE_WORKFLOW_NAME` for step images that still run an older kaos-lib.

## Inputs

`enhance.py` reads a `pipeline-context.yaml` the platform provides at release time: `app`,
`project`, `mlflow.*`, `lakefs.*`, `computeClasses.*`, `checkpoints.*`. `compose.py` and
`derive_tree.py` read the `platform` config group from the same place. The stand-ins used by
`./run.sh` on a laptop are in `local-dev/` and `config/`.

## Tests

`python -m pytest tests/` runs the engine tests offline: derivation, the `reads=` check,
group-swap handling, the ADVANCED override guard, enum validation, the size cap, byte-stable
output, the app-scoped name, the schema-rename check, the HPC (Slurm) leg.
