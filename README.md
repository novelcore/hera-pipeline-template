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
from kubecore.authoring import artifact, dataset, pipeline, step

with pipeline("ml-pipeline") as p:  # KAOS names it after your pipeline
    prepare = step("prepare", kind="transform", reads=["prepare"], inputs=["dataset"],
                   produces=[dataset("clean")])
    hello = step("hello-world", kind="evaluate", needs=[prepare], produces=[artifact("report")])
```

`prepare` reads the dataset version the run picked (the platform fixes it to one exact version before the
first step starts) and writes a new version of the dataset `dataset-<your app>-clean` (`<your app>` is the name of your app). `hello-world` reads exactly that
version and writes a report to your pipeline's `outputs-<app>` repository. **The `config/` tree is the run
form**: every plain value in `config/` becomes a field.

## A step in twenty lines

```python
# steps/hello_world/app/entry.py
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    clean = step.input("clean")  # the version of the dataset `clean` that `prepare` wrote in this run
    files = sum(1 for f in clean.rglob("*") if f.is_file() and not f.name.startswith("."))
    dropped = step.upstream("prepare").values["dropped"]  # a value `prepare` handed on
    line = f"{ctx.experiment}: {files} files in clean, {dropped} dropped by prepare"
    (step.output("report") / "hello.txt").write_text(line + "\n")
    print(f"[hello-world] {line}", flush=True)
    step.result(files=files)
```

A step takes no arguments and reads no environment variables. It names its inputs and outputs; the platform
chooses the versions, saves the files and hands the result to the next step
([The step API](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/step.html)).

### Long runs are not lost

A step on a reclaimed machine, a failed node or an HPC time limit is run again by the platform, and a training that
keeps its checkpoints in `KAOS_CHECKPOINT_DIR` (Ultralytics, Lightning and Hugging Face are picked up automatically
by `kaos_lib`) continues from the last one. You write nothing for this: see
[Long runs: checkpoints](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/checkpoint.html).

Your app is `pipeline.py`, `config/` and `steps/`. It holds no copy of the platform's pipeline engine:
the platform runs its own, and `kaosctl render`, `kaosctl step run` and `kaosctl dev` fetch the same one on your machine.

## Layout

```
pipeline.py            the steps and their order (kind=, reads=, inputs=, needs=, produces=, gpu=, when=)
config/                every setting; each one is a field on the run form
steps/<name>/          one folder per step: app/entry.py and a Dockerfile
step_tests/            tests of your step code (step_tests/README.md)
docs/                  the guide (mkdocs)
```

## Quick start

```bash
python3 -m venv ~/.venvs/kaos && . ~/.venvs/kaos/bin/activate
pip install --index-url https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/simple/ \
    --extra-index-url https://pypi.org/simple/ "kaos-lib[zitadel,mlflow]>=0.5"
kaosctl login                                    # inside the app folder
kaosctl render --context pipeline-context.yaml   # render the pipeline locally with the platform's engine
kaosctl dev                                      # one Python environment per step
kaosctl lint                                     # check pipeline.py, config/ and steps/
kaosctl step run prepare --input dataset=./my-data   # run one step on your machine
kaosctl step run hello-world                     # the next one reads what prepare wrote
kaosctl dataset push ./my-data dataset-my-data -m "first data"
```

`kaosctl` and the steps need kaos-lib **0.5** or newer
([install](docs/cookbook/4-install-kaosctl.md)).
The library is documented at [the kaos-lib reference](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html).

## Where to read next

| you want to | read |
|---|---|
| start from zero: access, apps, tools, data, pipeline, results | [the cookbook](docs/index.md) |
| make a dataset, run on it, find the result | [guide: first dataset and run](docs/first-run.md) |
| add a step that reads a dataset and writes a result | [guide: add a step](docs/guide-step-with-data.md) |
| save files from a step, or produce a dataset | [Write results from a step](docs/write-a-step.md) |
| change or add a setting | [Change a setting](docs/change-a-setting.md) |
| run a step on HPC (Slurm) | [Run on HPC (Slurm)](docs/hpc.md) |
| why the render refuses a service account or `podSpecPatch` | [Settings the platform owns](docs/platform-owned-settings.md) |

## Checking the docs

This is for the maintainers of the template. `make docs-check` (or `scripts/check-docs.sh`) runs three checks, then builds the site with `mkdocs build --strict`:

| check | fails on |
|---|---|
| words | a page that names what the platform is built from: the guide is for people who use the platform |
| removed names | a step or a folder that no longer exists |
| links | a link that does not resolve in this guide, in the kaos-lib guide or in the yolo guide, and a link from those two into this guide that does not resolve |

The checks are kaos-lib's `docs_check.py`; this repository holds no copy. The script downloads kaos-lib and the yolo template at their trunk, and stops with a message when a download fails. `DOCS_CHECK_KAOS_LIB=<folder>` and `DOCS_CHECK_YOLO=<folder>` read your own checkouts; `DOCS_CHECK_OFFLINE=1` checks this repository alone and prints what it skipped. Add `--external` to also check external links. Install the tools first: `pip install -r docs/requirements.txt`. No GitHub Actions needed. In an app created from this template the script checks nothing: it says so and ends.

One topic has one page. What is true for every pipeline (datasets, checkpoints, checking a step on your computer, kaos-lib versions) is in the [kaos-lib guide](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html); this guide holds what is specific to the template and links there.

## License

This project is licensed under the Apache License, Version 2.0. See the [LICENSE](LICENSE) file
for the full terms.
