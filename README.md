# hera-pipeline-template

A KAOS ML pipeline you write in **Python** ([Hera](https://github.com/argoproj-labs/hera)), with
its settings in a **[Hydra](https://github.com/facebookresearch/hydra) config tree**. Add your
steps and settings and open a pull request into `dev`. The platform checks it, builds your step
images on merge, and releases a pipeline you run from a web form. You never touch Kubernetes.

New ML apps are seeded from this template.

**The guide: [novelcore.github.io/hera-pipeline-template](https://novelcore.github.io/hera-pipeline-template/)**.
It is built around *the engineer's cookbook*, which takes you from your first sign-in to comparing
the trained weights of two runs.

## The pipeline in one file

```python
# pipeline.py
from kubecore.authoring import pipeline, step

with pipeline("ml-pipeline") as p:  # the platform renames it <app>-pipeline
    load  = step("dataset-loading", reads=["dataset"], outputs=["dataset-info"])
    hello = step("hello-world", reads=["experiment", "dataset"], needs=[load])
```

`dataset-loading` pins the dataset version the run picked to one commit. `hello-world` reads it
and writes a result to the app's `outputs-<app>` repository. **The `config/` tree is the submit
form**: every plain value in `config/` becomes a field.

## Layout

```
pipeline.py            the steps and their order (reads=, gpu=, needs=, outputs=, when=)
config/                every setting; each one is a field on the run form
steps/<name>/          one folder per step: app/entry.py and a Dockerfile
kubecore/              the platform's engine: seeded, do not edit
tests/, step_tests/    engine tests; step-code tests (DEVELOPER.md §15)
docs/                  the guide (mkdocs)
```

## Quick start

```bash
./run.sh                                         # render the pipeline locally, no cluster
python3 -m venv ~/.venvs/kaos && . ~/.venvs/kaos/bin/activate
pip install --index-url https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/simple/ \
    --extra-index-url https://pypi.org/simple/ "kaos-lib[zitadel,mlflow]>=0.4.0rc5"
kaosctl login                                    # inside the app folder
kaosctl dataset push ./my-data dataset-my-data -m "first data"
```

`kaosctl` needs kaos-lib **0.4.0rc5** or newer
([install](https://novelcore.github.io/hera-pipeline-template/cookbook/4-install-kaosctl/)).
The library is documented at [the kaos-lib reference](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html).

## Where to read next

| you want to | read |
|---|---|
| start from zero: access, apps, tools, data, pipeline, results | [the cookbook](https://novelcore.github.io/hera-pipeline-template/) |
| make a dataset, run on it, find the result | [guide: first dataset and run](https://novelcore.github.io/hera-pipeline-template/first-run/) |
| add a step that reads the dataset | [guide: add a step](https://novelcore.github.io/hera-pipeline-template/guide-step-with-data/) |
| run a step on MeluXina | [MeluXina](https://novelcore.github.io/hera-pipeline-template/meluxina/) |
| the operating manual: config, tests, HPC | [DEVELOPER.md](DEVELOPER.md) |
| how the platform works inside | [MECHANISMS.md](MECHANISMS.md), [PLATFORM.md](PLATFORM.md) |

## License

This project is licensed under the Apache License, Version 2.0. See the [LICENSE](LICENSE) file
for the full terms.
