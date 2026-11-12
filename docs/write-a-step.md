# Write results from a step

**Goal:** a step that saves files, so that the next step, a later run and you can read them.

**You need:** a step that installs kaos-lib ([Add a step](add-a-step.md)). Both steps of the template
write this way: `steps/prepare/` writes a dataset and `steps/hello_world/` writes a report. Copy them.

## 1. Declare what the step writes

In `pipeline.py`, name each output in `produces=`:

```python
from kubecore.authoring import artifact, dataset, model, pipeline, step

prepare = step("prepare", kind="transform", inputs=["dataset"], produces=[dataset("clean")])
train = step("train", kind="train", needs=[prepare], gpu=True, produces=[model("model")])
report = step("report", kind="evaluate", needs=[train], produces=[artifact("report")])
```

| you declare | use it for | it is saved as |
|---|---|---|
| `dataset("clean")` | data that later steps and later runs read | a new version of the dataset `dataset-<your app>-clean` |
| `model("model")` | trained weights | files in `outputs-<app>` under `model/<experiment>/<run>/` |
| `artifact("report")` | everything else: reports, plots, tables | files in `outputs-<app>` under `report/<experiment>/<run>/` |

A name uses lowercase letters, digits and hyphens.

## 2. Write the files

```python
from kaos_lib import step

ctx = step.start()
folder = step.output("report")                  # an empty folder; what it holds is saved
(folder / "summary.txt").write_text("42 rows\n")
step.result(rows=42)                            # saves every output, then hands rows=42 on
```

- `step.output("<name>")` gives a folder. Write into it with any library.
- Nothing is saved before `step.result()`. A step that fails saves nothing, so nobody reads half a result.
- Every output you declared must hold at least one file, or the step fails and says which one is empty.
- You never name a repository, a path or a commit. The platform knows them from `produces=`.

## 3. Read them in the next step

```python
data = step.input("clean")                      # what the step you need wrote in this run: a folder
rows = step.upstream("prepare").values["rows"]  # the small values it handed on
```

The step that reads names the step that wrote in `needs=`. It gets exactly what was written in this run, also
when another run writes the same dataset at the same time.

## 4. A dataset your step produces

A step that declares `dataset("clean")` makes one new version of `dataset-<your app>-clean` in every run (`<your app>` is
the name of your app; your code only ever uses the short name `clean`). The platform creates the dataset for your
pipeline, and only your pipeline can write it.

- Write every file under the same path in every run. Then a run that changes one file uploads one file.
- The newest version (`latest`) moves to a run's version only when the run asks for it: the run form has that
  choice for each dataset the pipeline produces. A run that does not ask still writes its version, and its own
  later steps read it.
- Another pipeline reads the dataset like any other: a setting such as `clean: "dataset-<your app>-clean"` named in
  `inputs=`.

The whole story is in [A dataset a step produces](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/steps-and-datasets.html#a-dataset-a-step-produces).

## 5. Long steps

A training step that runs for hours keeps its checkpoints in the folder the platform gives it and continues from
the last one after a lost machine or a time limit, with nothing to call
([Long runs: checkpoints](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/checkpoint.html)). It writes its final weights into `step.output("model")` like any
other output.

## 6. Test it on your laptop

`kaosctl step run <step>` runs the step on your machine and keeps what it wrote in `.kaos/local/`
([Run a step locally](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/step-run.html)). `python -m pytest` runs the template's own step tests the same way: see
`step_tests/README.md`.

**Next:** [Results](results.md). The full list of calls and messages: [The step API](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/step.html).
