# Your pipeline

A Python pipeline file, a config tree that becomes the run form, and one folder for each step. It holds two steps that run
as they are: `prepare` keeps the files of a dataset that are not empty and writes them as the dataset `clean`, and
`hello-world` reads `clean` and writes a small report.

## The files that matter

| path | what it is |
|---|---|
| `pipeline.py` | the steps and their order |
| `config/` | every setting; each plain value is a field on the run form |
| `steps/<name>/` | one folder for each step: `app/entry.py` and a `Dockerfile` |
| `step_tests/` | tests of your steps, see [`step_tests/README.md`](step_tests/README.md) |

`examples/gpu_check/` is a GPU step to copy into `steps/`: see
[Bigger machines](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/bigger-machines.html).
`.kaos/compat.yaml` holds the range of kaos-lib versions your code works with.

## Run it on your machine

Install kaos-lib at the version the step images use, then run every step test, which runs the steps the way the platform does:

```bash
pip install "$(sed -n 's/^ARG KAOS_LIB_PACKAGE="\(.*\)"$/\1/p' steps/*/Dockerfile | head -1)" pytest && python -m pytest
```

To run one step by hand, use [`kaosctl step run`](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/try-it-locally.html#run-steps-the-way-the-platform-does).

## The guide

[Run it](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/run-it.html) creates a pipeline, runs it, and changes
it one idea at a time, from a first step to a pipeline of your own. For a larger pipeline see the
[yolo pipeline](https://github.com/novelcore/yolo-pipelines-template).

To add files to the dataset `prepare` reads, or change them, see [Add or change data](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/add-or-change-data.html). To give
them a version and pin it, see [Release a dataset version](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/release-a-version.html).
