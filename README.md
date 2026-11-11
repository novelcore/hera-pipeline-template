# hera-pipeline-template

**hera** is the starter ("scaffold") template for ML pipelines on KAOS. You write the pipeline in
**Python** ([Hera](https://github.com/argoproj-labs/hera)), keep its settings in a
**[Hydra](https://github.com/facebookresearch/hydra) config tree**, and push to your pipeline's
code repository. KAOS builds your steps and gives you a run form. You never touch servers.
For object detection there is a ready-made template built on hera:
[yolo](https://github.com/novelcore/yolo-pipelines-template).

## Start here

You were given a KAOS account and a project? Follow **[the cookbook](docs/index.md)**. It goes from
your first sign-in to comparing the trained weights of two runs.

The same guide is published at <https://novelcore.github.io/hera-pipeline-template/>. That site
shows the **released** version, so a page that is new here may not be there yet. Links inside this
repository are relative and work on any branch.

### The 5-minute path

1. Sign in to the KAOS console. **Machine learning** is in the sidebar ([1. You're in](docs/cookbook/1-youre-in.md)).
2. Install `kaosctl` and run `kaosctl login` ([4. Install kaosctl](docs/cookbook/4-install-kaosctl.md)).
3. Create a dataset, upload data, release `v1` ([5. Your data](docs/cookbook/5-your-data.md)).
4. Create your pipeline from this template: **Pipelines**, **New pipeline** ([2. Your project's apps](docs/cookbook/2-your-apps.md)).
5. Open the run form, pick `dataset-<name>@v1`, press **Submit** ([7. Run it](docs/cookbook/7-run-it.md)).
6. Open the run in MLflow ([8. Results and weights](docs/cookbook/8-results-and-weights.md)).

## The pipeline in one file

```python
# pipeline.py
from kubecore.authoring import pipeline, step

with pipeline("ml-pipeline") as p:  # KAOS names it after your pipeline
    hello = step("hello-world", reads=["experiment", "dataset"])
```

`hello-world` reads the dataset version the run picked (the platform pins it to one commit before the
first step starts) and writes a result to your pipeline's `outputs-<app>` repository. **The `config/` tree is the run
form**: every plain value in `config/` becomes a field.

### Long runs are not lost

A step on a reclaimed machine, a failed node or an HPC time limit is run again by the platform, and a training that
keeps its checkpoints in `KAOS_CHECKPOINT_DIR` (Ultralytics, Lightning and Hugging Face are picked up automatically
by `kaos_lib`) continues from the last one. You write nothing for this: see
[When a machine is lost or a time limit hits](docs/resilience.md).

Your app is `pipeline.py`, `config/` and `steps/`. It holds no copy of the platform's pipeline engine:
the platform runs its own, and `kaosctl render`, `kaosctl step run` and `kaosctl dev` fetch the same one on your machine.

## Layout

```
pipeline.py            the steps and their order (reads=, gpu=, needs=, outputs=, when=)
config/                every setting; each one is a field on the run form
steps/<name>/          one folder per step: app/entry.py and a Dockerfile
step_tests/            tests of your step code (DEVELOPER.md §15)
docs/                  the guide (mkdocs)
```

## Quick start

```bash
python3 -m venv ~/.venvs/kaos && . ~/.venvs/kaos/bin/activate
pip install --index-url https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/simple/ \
    --extra-index-url https://pypi.org/simple/ "kaos-lib[zitadel,mlflow]>=0.4.0rc5"
kaosctl login                                    # inside the app folder
kaosctl render --context pipeline-context.yaml   # render the pipeline locally with the platform's engine
kaosctl dev                                      # one Python environment per step
kaosctl step run hello-world                     # run one step on your machine
kaosctl dataset push ./my-data dataset-my-data -m "first data"
```

`kaosctl` needs kaos-lib **0.4.0rc5** or newer
([install](docs/cookbook/4-install-kaosctl.md)).
The library is documented at [the kaos-lib reference](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html).

## Where to read next

| you want to | read |
|---|---|
| start from zero: access, apps, tools, data, pipeline, results | [the cookbook](docs/index.md) |
| make a dataset, run on it, find the result | [guide: first dataset and run](docs/first-run.md) |
| add a step that reads the dataset | [guide: add a step](docs/guide-step-with-data.md) |
| run a step on HPC (Slurm) | [Run on HPC (Slurm)](docs/hpc.md) |
| the operating manual: config, tests, HPC | [DEVELOPER.md](DEVELOPER.md) |
| why the render refuses a service account or `podSpecPatch` | [Settings the platform owns](docs/platform-owned-settings.md) |

## Checking the docs

`make docs-check` (or `scripts/check-docs.sh`) builds the site with `mkdocs build --strict` and checks every internal link and anchor. Add `--external` to also check external links. Install the tools first: `pip install -r docs/requirements.txt`. No GitHub Actions needed.

## License

This project is licensed under the Apache License, Version 2.0. See the [LICENSE](LICENSE) file
for the full terms.
