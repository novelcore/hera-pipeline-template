# Datasets

## What a dataset is

A dataset is a **lakeFS repository** named `dataset-<name>`. Your project starts with one,
`dataset-default`.

| thing | what it is |
|---|---|
| version | a tag on `main`: `v1`, `v2`, … |
| `latest` | the newest data on `main` |
| change | a pull request into `main`, reviewed and merged by a person |
| pick | `dataset = <repository>@<version>` in the run form |
| results | never written to a dataset: they go to `outputs-<app>` |

A run reads **one commit**: the one its pick resolves to. Merging new data while a run is
going does not change what that run reads.

## Picking a dataset in the pipeline

The template's `config/dataset.yaml` defines the field:

```yaml
dataset: "dataset-default@latest"
```

On the Argo form it becomes a dropdown of the `<dataset>@<version>` choices of your project,
newest first, with the default dataset first. Keep a field named exactly `dataset`, and give
the steps that need it `reads=["dataset"]`.

Anything that is not `<repository>@<version>` is refused before the run starts, with a
message that says what is wrong and what exists.

## Templates are optional

`kubecore dataset create <name>` starts a repository from a **format template**. The only one
today is `yolo` (YOLO, images + labels: `data.yaml`, `images/`, `labels/`); a template is the
starter layout plus the checks `validate` and `push` run.

You can do without it:

- `kubecore dataset create <name> --template none` makes an empty `dataset-<name>`.
- A repository named `dataset-<something>` created by hand in lakeFS becomes a dataset after
  its first commit.
- A repository with **no template label validates nothing**; `push` takes the files as they are.
  Pass `--format yolo` to `push` or `validate` to get the YOLO checks anyway.
- Code can read **any** repository: `datasets.materialize("<repo>@<ref>")` with `<ref>` one of
  `vN`, `latest`, a branch, a tag or a commit id. The dropdown lists only `dataset-*`
  repositories.

## The commands

```bash
kubecore login
kubecore dataset create <name> [--classes a,b] [--template yolo|none]
kubecore dataset list
kubecore dataset versions <repo>
kubecore dataset pull <repo>@<ref> [dir] [--prefix folder/]
kubecore dataset validate <dir> --format yolo
kubecore dataset push <dir> <repo> -m "message" [--format yolo]
kubecore dataset release <repo>
```

Every command prints the next step and the link to what it made. Exit codes: 0 ok, 1 something
for you to fix (one `ERROR:` line), 2 an invalid dataset.

!!! note "Who may do what"
    Reading a dataset needs read rights, which a pipeline has. Creating a dataset, pushing, and
    releasing a version are for people, not for the pipeline: a step can never write to a dataset.

## Formats and what `materialize` returns

| the repository's label (`kaos.template`) | `materialize` returns |
|---|---|
| `yolo` | the local `data.yaml`, ready to train on |
| none | a local folder with the files at that commit (`prefix=` for one folder) |

The first call downloads and keeps the copy by repository and commit; the next call is free. On
MeluXina the platform has staged the commit already and `materialize` uses that copy.

`datasets.format_of("<repo>")` tells you which one a repository is.
