# 6. Your pipeline

**Goal:** you know how the pipeline is put together, you have run the shipped pipeline twice, and
your own step is added, checked and live.

**Who can do it:** `dev`, `ops` or `admin`. You push branches and merge pull requests on GitHub,
and you submit runs from the run form.

## How it is put together

```
pipeline.py            the steps, what each one reads and writes, and their order: nothing else
config/                every setting; each one becomes a field on the run form
  config.yaml            which files and groups make up the settings
  experiment.yaml        experiment.name, experiment.description
  dataset.yaml           dataset: "dataset-default"  (the dataset field of the form)
  prepare.yaml           prepare.min_bytes
steps/<step_name>/     one folder per step: app/entry.py and a Dockerfile
```

The shipped `pipeline.py` has two steps:

```python
with pipeline("ml-pipeline") as p:   # KAOS names it <app>-pipeline
    prepare = step("prepare", kind="transform", reads=["prepare"], inputs=["dataset"],
                   produces=[dataset("clean")])
    hello = step("hello-world", kind="evaluate", needs=[prepare], produces=[artifact("report")])
```

- **`prepare`** reads the run's dataset, at the one version the platform fixed when the run
  started, and writes the files of at least `prepare.min_bytes` bytes as a new version of the dataset
  `dataset-<your app>-clean`.
- **`hello-world`** reads exactly the version `prepare` wrote in this run, counts its files and
  writes a small `hello.txt` to `outputs-<app>`.

| in `step(...)` | means |
|---|---|
| `kind=` | what the step is: `ingest`, `transform`, `train`, `evaluate`, `publish` or `control` |
| `reads=` | the sections of `config/` the step gets |
| `inputs=` | the settings that hold a dataset the step reads |
| `needs=` | the steps that run before it; it can read what they wrote |
| `produces=` | what the step writes: `dataset("...")`, `model("...")` or `artifact("...")` |

Each step's code is about twenty lines. Open `steps/prepare/app/entry.py` and
`steps/hello_world/app/entry.py`: everything they get from the platform comes from `kaos_lib.step`
([The step API](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/step.html)). [How it works](../how-it-works.md) explains the rest.

## Run the shipped pipeline on your dataset

Before you change anything, prove the pipeline works. Console → **Pipelines** →
your app → **Run**. In the **`dataset`** field pick `dataset-cats@v1` (from
[chapter 5](5-your-data.md)) and press **Submit** ([chapter 7](7-run-it.md)).

**You should see** both steps go green, and in their logs:

```
[prepare] kept 120 of 120 files
[hello-world] my-experiment-v1: 120 files in clean, 0 dropped by prepare
```

and a new `hello.txt` in `outputs-<app>` ([chapter 8](8-results-and-weights.md)).

The form's default, `dataset-default`, is empty until you put files in it. On an empty dataset `prepare`
stops and its log ends with `dataset-default@latest holds no files`: pick a dataset that has files.

## Add a step

Make the folder, write the entry point and the Dockerfile, and add one line to `pipeline.py`:

```python
    mine = step("my-step", kind="evaluate", inputs=["dataset"])
```

The step name uses dashes (`my-step`); its folder uses underscores (`steps/my_step/`). Follow
[Add a step that reads a dataset and writes a result](../guide-step-with-data.md) for the whole
thing, or [Add a step](../add-a-step.md) for a step with no data. To take one out, see
[Remove a step](../remove-a-step.md).

## Change a setting

Add a line under a section in `config/`, and the form gets a field with that name, with dots turned
into dashes:

```yaml
# config/experiment.yaml
experiment:
  name: "my-experiment-v1"
  description: ""
  rounds: 3                # the form gets experiment-rounds, default 3
```

See [Change a setting](../change-a-setting.md).

## Push, check, go live

```bash
git checkout -b add-my-step dev
git add pipeline.py steps/my_step config
git commit -m "add my-step"
git push -u origin add-my-step
```

Open a pull request **into `dev`**. Then:

1. **`wft-render`** runs on the pull request. It renders your pipeline the way KAOS will
   build it: the steps are wired, every `reads=` names a config section that exists, and every step
   has a `steps/<dir>/Dockerfile`. It reports as a status check on the pull request. **Details**
   opens the run with the error, or with the rendered pipeline when it passes
   ("pipeline rendered: N steps, M form params").
2. **Merge** when it is green.
3. **`kubecore-ml-ci`** runs on the merge. It builds the step images whose folders changed and
   releases a new version of `<app>-pipeline`. It reports on the merge commit, and in the console
   under **CI builds**.

When `kubecore-ml-ci` is green, the form has your step and your new field
([Send your change in](../send-it-in.md)).

## If it isn't there

| symptom | fix |
|---|---|
| `wft-render` red: a step has no Dockerfile | add `steps/<step_name>/Dockerfile`; the folder uses underscores |
| `wft-render` red: a section in `reads=` does not exist | fix the name in `reads=`, or add the section to `config/` |
| `wft-render` never appears | the pull request is not into `dev` |
| your new field is not on the form | only plain values become fields (text, numbers, true/false); reopen the form after `kubecore-ml-ci` is green |
| a step did not rebuild | only steps whose folder changed are rebuilt; that is expected |

**Next:** [7. Run it](7-run-it.md).
