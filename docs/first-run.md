# First dataset, first run, your results

This page takes you from nothing to a finished run and its results, with every command. It
uses the pipeline that ships in this template (`dataset-loading`, then `hello-world`), so
you can do it before you write any code of your own.

You need your app cloned on your computer ([Get the project](get-the-project.md)) and
Python 3.9 or newer.

## 1. Install the tool and sign in

The `kubecore` tool is a Python package. Install it once, inside a small private Python
space for this project (a "virtual environment"), in your app folder.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install "kubecore[zitadel] <version>"
kubecore login
```

`<version>` is the value of `KAOS_LIB_PACKAGE` in `steps/hello_world/Dockerfile`, for
example `@ https://github.com/novelcore/hera-pipeline-template/archive/<commit>.zip#subdirectory=packages/kubecore`
([Package versions and upgrades](kaos-lib-versions.md)). On Windows, the second line is `.venv\Scripts\activate`.
Your browser opens once and asks you to sign in. Log in, close the tab, and go back to the
Terminal. The tool remembers you.

!!! tip "Why the virtual environment?"
    Many computers no longer let `pip install` change the system's own Python (a message
    that mentions `externally-managed-environment`). The virtual environment avoids that.

Run every `kubecore` command inside your app folder: it carries `.kubecore/dataset-config.yaml`,
which tells the tool where your project's lakeFS is. You never need a link or a password.

## 2. Create a dataset

```bash
kubecore dataset create cats --classes cat,kitten
```

This makes the lakeFS repository `dataset-cats` with a starter layout for the
`ultralytics` (YOLO) format: `data.yaml`, `images/` and `labels/`. The command prints a
link to it.

!!! note "Templates are optional"
    You do not have to use a template. `kubecore dataset create cats --template none`
    makes an empty `dataset-cats`, and a `dataset-*` repository you create by hand in
    lakeFS becomes a dataset after its first commit. The rest of this page works the same.

## 3. Put your files in

Download the dataset, add your files, check them, and send them back.

```bash
kubecore dataset pull dataset-cats@latest ./dataset-cats
# copy your images into ./dataset-cats/images/train and images/val
# and one label file per image into ./dataset-cats/labels/train and labels/val
kubecore dataset validate ./dataset-cats --format ultralytics
kubecore dataset push ./dataset-cats dataset-cats -m "first 200 images"
```

- `validate` lists every problem it finds (a label for no image, a class number outside
  `names`, and so on). Fix them and run it again.
- `push` uploads your folder to a draft and opens a **pull request**. It prints the link.
- A repository with no template label validates nothing; add `--format ultralytics` to
  `push` as well to get the YOLO checks there.

## 4. Merge the pull request and release a version

Open the pull request link, look at the change, and merge it. Nothing changes on `main`
until you do. Then tag the new state as a version:

```bash
kubecore dataset release dataset-cats      # prints v1
kubecore dataset versions dataset-cats
```

A run reads a version, not "whatever is there now", so a result always points back to its
data.

## 5. Run the pipeline on it

Open your pipeline in the Argo UI and submit it ([Run your pipeline](run-it.md)). The form has
a field called **`dataset`**, a dropdown of `<dataset>@<version>` choices:

```
dataset-cats@v1
dataset-cats@latest
dataset-default@latest
```

Pick `dataset-cats@v1`. If the new version is not in the list yet, wait a few minutes: the
list is refreshed when a dataset or a version changes.

The first step, `dataset-loading`, turns your choice into one commit. Every later step reads
that commit, even if someone merges a new change to `dataset-cats` while the run is going.

## 6. Find your results

Each app has its own repository, `outputs-<app>`. When the run finishes, every step that
wrote results has added **one commit** to its `main` branch, under
`checkpoints/<experiment>/<run>/` (`experiment` is the `experiment-name` field you set,
`run` is the name of the Argo run).

Open `outputs-<app>` in lakeFS, branch `main`, folder `checkpoints`. The example step wrote a
small `hello.json` there, naming the dataset and the commit it read. To get the files on your
computer:

```bash
kubecore dataset pull outputs-<app>@main ./results --prefix checkpoints/<experiment>/<run>/
```

The commit's message and details name the run, the dataset and its commit, so you can find
out later what any result was trained on.

## What next

- How datasets, versions and templates fit together: [Datasets](datasets.md).
- Writing your own step that reads a dataset and writes results: [Write a step that uses a dataset](write-a-step.md).
- Using a MeluXina class for a step: the "Running on MeluXina" section of the README.
