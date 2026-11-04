# 6. Your pipeline

**Goal:** you know how the pipeline is put together, you have run the shipped pipeline twice, and
your own step is added, checked and live.

**Who can do it:** `dev`, `ops` or `admin`. You push branches and merge pull requests on GitHub,
and you submit runs in Argo.

## How it is put together

```
pipeline.py            the steps and their order: nothing else
config/                every setting; each one becomes a field on the run form
  config.yaml            which files and groups make up the settings
  experiment.yaml        experiment.name, experiment.description
  dataset.yaml           dataset: "dataset-default@latest"  (the dropdown)
steps/<step_name>/     one folder per step: app/entry.py and a Dockerfile
kaos_pipeline/         helper code that ships with the template; do not edit
```

The shipped `pipeline.py` has two steps:

```python
with pipeline("ml-pipeline") as p:   # KAOS names it <app>-pipeline
    load  = step("dataset-loading", reads=["dataset"], outputs=["dataset-info"])
    hello = step("hello-world", reads=["experiment", "dataset"], needs=[load])
```

- **`dataset-loading`** turns the run's `dataset` pick into one lakeFS commit and hands it on as
  `dataset-info`.
- **`hello-world`** reads that commit and writes a small `hello.json` to `outputs-<app>`.

`reads=` lists the config sections a step receives, `needs=` sets the order, and `outputs=` names
the small results it hands to later steps. [How it works](../how-it-works.md) explains the rest.

## Run the shipped pipeline on `dataset-default`

Before you change anything, prove the pipeline works. Argo → **Workflow Templates** →
`<app>-pipeline` → **Submit**. Leave every field as it is and press **Submit**
([chapter 7](7-run-it.md)).

**You should see** both steps go green. `dataset-default` is still empty, so the `hello-world` log
says:

```
[hello-world] dataset-default@latest @ <commit> holds no files yet. Add yours with `kaosctl dataset push <folder> <dataset>` ...
[hello-world] result committed to outputs: <commit>
```

An empty dataset is reported, not an error, so the run still succeeds.

## Run it on your dataset

Submit again, and in the **`dataset`** dropdown pick `dataset-cats@v1` (from
[chapter 5](5-your-data.md)). **You should see** the log name your dataset, its commit and its
classes, and a new `hello.json` in `outputs-<app>`
([chapter 8](8-results-and-weights.md)).

## Add a step

Make the folder, write the entry point and the Dockerfile, and add one line to `pipeline.py`:

```python
    mine = step("my-step", reads=["experiment", "dataset"], needs=[load])
```

The step name uses dashes (`my-step`); its folder uses underscores (`steps/my_step/`). Follow
[Add a step that reads the dataset and writes a result](../guide-step-with-data.md) for the whole
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
   opens the Argo run with the error, or with the rendered pipeline when it passes
   ("pipeline rendered: N steps, M form params").
2. **Merge** when it is green.
3. **`kaos-ml-ci`** runs on the merge. It builds the step images whose folders changed and
   releases a new version of `<app>-pipeline`. It reports on the merge commit, and in the console
   under **CI builds**.

When `kaos-ml-ci` is green, the form has your step and your new field
([Send your change in](../send-it-in.md)).

## If it isn't there

| symptom | fix |
|---|---|
| `wft-render` red: a step has no Dockerfile | add `steps/<step_name>/Dockerfile`; the folder uses underscores |
| `wft-render` red: a section in `reads=` does not exist | fix the name in `reads=` and in the step's `READS`, or add the section to `config/` |
| `wft-render` never appears | the pull request is not into `dev` |
| your new field is not on the form | only plain values become fields (text, numbers, true/false); reopen the form after `kaos-ml-ci` is green |
| a step did not rebuild | only steps whose folder changed are rebuilt; that is expected |

**Next:** [7. Run it](7-run-it.md).
