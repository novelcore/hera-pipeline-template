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
guide page: bigger-machines.
`.kaos/compat.yaml` holds the range of kaos-lib versions your code works with.

## Run it on your machine

Install `kaosctl` with pip from your platform's package index. Your platform admin, or the console of your platform, gives you the index and the version to install. To move to a newer version later, run `kaosctl upgrade`. Then run every step test, which runs the steps the way the platform does:

```bash
pip install pytest && python -m pytest
```

To run one step by hand, use `kaosctl step run` (guide page: try-it-locally).

## The guide

The guide page run-it creates a pipeline, runs it, and changes
it one idea at a time, from a first step to a pipeline of your own. For a larger pipeline see the
[yolo pipeline](https://github.com/novelcore/yolo-pipelines-template).

To add files to the dataset `prepare` reads, or change them, see the guide page add-or-change-data. To give
them a version and pin it, see the guide page release-a-version.
