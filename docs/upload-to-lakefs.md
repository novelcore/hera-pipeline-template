# Datasets in lakeFS

A dataset is its own lakeFS repository, called `dataset-<name>`. Your project starts with one, `dataset-default`. A run does not read "whatever is there now": it picks a **version** of one dataset, and every step of that run reads exactly that version.

- A **version** is a tag, `v1`, `v2`, and so on. `latest` means the newest data on `main`.
- Changes reach `main` only through a **pull request**, so someone reviews them before they become the new data.
- Your results are never written to a dataset. They go to your app's own repository, `outputs-<app>`.

You do this with the `kubecore` command.

## Step 1. Install the tool and sign in

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install "git+https://github.com/novelcore/hera-pipeline-template@<commit>#subdirectory=packages/kubecore"
kubecore login
```

On Windows, the middle line is `.venv\Scripts\activate` instead. Your browser opens once for the sign-in; the tool remembers you. It finds your project's lakeFS from the file `.kubecore/dataset-config.yaml` in your app folder, so run the commands inside your app folder.

!!! tip "Why the virtual environment?"
    Many computers no longer let `pip install` change the system's own Python (a message that mentions `externally-managed-environment`). The virtual environment avoids that.

## Step 2. Create a dataset and send your files in

```bash
kubecore dataset create cars --classes car,truck,bus      # makes dataset-cars with the starter layout
kubecore dataset pull dataset-cars@latest ./dataset-cars   # a local copy to add your files to
# add images to images/train and images/val, one label file per image in labels/...
kubecore dataset validate ./dataset-cars                   # checks the layout before you send it
kubecore dataset push ./dataset-cars dataset-cars -m "first 200 images"
```

`push` opens a pull request and prints its link. Open it in lakeFS and merge it when it looks right. Nothing changes on `main` until you do.

## Step 3. Release a version

```bash
kubecore dataset release dataset-cars     # tags the head of main as the next version: v1, then v2, ...
kubecore dataset versions dataset-cars
kubecore dataset list                     # every dataset you can see
```

The run page's `dataset` field is a dropdown of `dataset-<name>@<version>` choices (newest first, then `@latest`). A new version shows up the next time your pipeline is released.

## Step 4. Read the data in a step

Your pipeline has a `dataset` field (`config/dataset.yaml`). The first step, `dataset-loading`, turns the choice into one commit and passes it on as `--dataset-info`. A later step reads that commit with the package:

```python
from kubecore import datasets
from kubecore.formats import get_format

ref = datasets.DatasetRef.parse(info["dataset"])            # "dataset-cars@v1"
data_yaml = get_format("ultralytics").consumer.materialize(ref)   # a local data.yaml you can train on
```

`materialize` downloads only `data.yaml`, `images/` and `labels/`, and keeps the copy for next time. On MeluXina the platform has already copied the version to the machine, and the same call uses that copy.

## Step 5. Write results

```python
from kubecore import outputs
outputs.write_run("my-app", experiment, run_id, "./results")   # one commit on outputs-my-app
```

The files appear under `checkpoints/<experiment>/<run>/` in `outputs-<app>`. Call it once per step per run. The template steps (`steps/hello_world/app/entry.py`) show the whole flow.

## If something goes wrong

- **The browser sign-in fails or never opens.** Copy the link the tool printed into your browser.
- **`not a dataset reference`.** Write `<dataset-repo>@<version>`, for example `dataset-cars@v1`.
- **`has no version v3`.** The message lists the versions that exist. Release one with `kubecore dataset release`.
- **`nothing new to release`.** Merge your pull request first; the head of `main` is already a version.
