# Change a setting

A setting is any value a person might want to change before a run. The name of an experiment. A number of rounds. A threshold. You keep settings in the `config/` folder.

Here is the part that feels like magic. Every setting you write in `config/` shows up as a field on the run page. You write one line. A field appears. There is no extra wiring.

## Look at what is there

Open `config/experiment.yaml`. It looks like this.

```yaml
experiment:
  name: "my-experiment-v1"
  description: ""
```

Two settings. `name` and `description`. On the run page these become two fields called `experiment-name` and `experiment-description`. The rule for the field name is simple. Take the path, replace the dots with dashes.

![The experiment-name and experiment-description fields on the run form](img/form-experiment-fields.png)

## Add a new setting

Say you want people to choose a number of rounds. Add one line under `experiment`.

```yaml
experiment:
  name: "my-experiment-v1"
  description: ""
  rounds: 3
```

Save the file. That is the whole change. After you send it in, the run page will have a new field called `experiment-rounds` with a default of `3`.

A step reads it when it names the section in `reads=`:

```python
# pipeline.py
step("my-step", kind="train", reads=["experiment"])
```

```python
# steps/my_step/app/entry.py
ctx = step.start()
print(ctx.params["experiment"]["rounds"])
```

A step gets the sections it names in `reads=` and no other. The template's `prepare` step does this with
`config/prepare.yaml`: its form field is `prepare-min_bytes`.

## Change a default

Want a different starting value. Just edit the number.

```yaml
  rounds: 5
```

Now the field shows up with `5` already filled in. People can still change it on the run page. You only changed the starting point.

## What can be a setting

Keep it to simple values. These work well.

- Text, like a name.
- Numbers, like `3` or `0.5`.
- True or false.

These do not work as fields.

- Long lists.
- Big blocks of nested data.

If you need one of those, use a dropdown of preset choices instead (below).

## Dropdowns

Sometimes you want a person to pick from a fixed set of choices rather than type free text. That is a dropdown. You make one with a folder of choice files instead of a single value: every file in `config/<group>/` is one option, and `config/config.yaml` names the default in its `defaults` list.

```yaml
# config/train/optimizer/sgd.yaml: one option
name: "SGD"
lr: 0.01
```

```yaml
# config/config.yaml
defaults:
  - _self_
  - experiment
  - train
  - train/optimizer: sgd      # the default option
```

The form then shows one dropdown, `train-optimizer`, with one option per file. Picking an option changes every value in its file together. To add an option, add a file. A field you change by hand on the form wins over the option you picked.

## Things people ask

| question | answer |
|---|---|
| my new setting is not on the form | it is inside a list or a nested block of data. Only single values and dropdowns become fields |
| what is the field called | the setting's path with dashes between the levels: `train.loss.weight` is `train-loss-weight` |
| I renamed a section and the check on my request fails | a step still names the old section in `reads=`; the message names the step |
| my step gets a `KeyError` for a section | the section is missing from the step's `reads=` |
| true and false | plain values: `enabled: true` in the file, `true` or `false` on the form, a real boolean in the step |
| can I put a file's content or a long list in a setting | no. Settings are for small values; data goes into a dataset or an output |
| I changed only `config/` and no step was rebuilt | that is right: a step is rebuilt only when its own folder changed |

Next, send your change in. Go to [Send your change in](send-it-in.md).
