# hera pipeline template

hera is the starter template for ML pipelines. You write the pipeline in Python, keep its settings in a config tree, and
the platform builds your steps and gives you a run form. The template holds two steps, `prepare` and `hello-world`, that
run as they are.

**Start with the guide: [Run it](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/run-it.html).** It creates a pipeline from this template, runs it, and
changes it one idea at a time, from a first step to a pipeline of your own. The guide is
[kaos-lib's](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html); this site holds only what is specific to the template.

## What the template holds

| path | what it is |
|---|---|
| `pipeline.py` | the steps and their order: `prepare` reads a dataset and writes the dataset `clean`, `hello-world` reads `clean` and writes a report |
| `config/` | every setting; each plain value is a field on the run form |
| `steps/prepare/`, `steps/hello_world/` | one folder for each step: `app/entry.py` and a `Dockerfile` |
| `examples/gpu_check/` | a GPU step to copy into `steps/`: [Bigger machines](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/bigger-machines.html) |
| `step_tests/` | tests of the two steps: [Try it locally](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/try-it-locally.html) |

For training object detection models there is a pipeline built from this template: the
[yolo pipeline guide](https://novelcore.github.io/yolo-pipelines-template/).
