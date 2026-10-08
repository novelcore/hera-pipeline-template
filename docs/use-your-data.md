# Use your own data

Your steps can read a dataset from lakeFS, the project's data storage. This page shows you how to put a folder of files there, and how a step reads it back. Any kind of files works: images, CSV, text.

## Step 1. Install the upload tool

The upload tool is already in your project, in a folder called `dataset_tools`. Install it once, inside a small private Python space for this project (a "virtual environment"). Run these in your project folder.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install ./dataset_tools
```

On Windows, the middle line is `.venv\Scripts\activate` instead.

Next time, just run the middle line again before uploading.

!!! tip "Why the extra two lines?"
    Many computers no longer let `pip install` change the system's own Python. They stop with a message that mentions `externally-managed-environment`. The virtual environment avoids that.

## Step 2. Upload your folder

```bash
python3 scripts/upload-dataset.py /path/to/your-folder
```

Replace `/path/to/your-folder` with the real folder on your computer. You do not pass any links. Your project already knows its lakeFS.

The first time, your browser opens and asks you to sign in. Sign in, close the tab, and go back to the Terminal. The tool remembers you.

The tool uploads the folder as the dataset called `main`, and saves it. To keep more than one dataset, give each one a name after the folder:

```bash
python3 scripts/upload-dataset.py /path/to/your-folder my-data-v1
```

!!! warning "Same name replaces"
    Uploading again with a name you already used makes that dataset match your folder. Files you do not have on your computer are removed from it. The tool shows you which files and asks before it removes anything. To keep the old one, pick a new name.

## Step 3. Add the dataset fields to the run page

Create `config/data.yaml`:

```yaml
data:
  ref: "main"      # which dataset: the name you uploaded with
  version: ""      # leave empty, unless you uploaded with --data-version
```

Then add `- data` to the list in `config/config.yaml`, under `- experiment`:

```yaml
defaults:
  - _self_
  - experiment
  - data
  - platform: live
```

The run page now has a `data-ref` field and a `data-version` field.

## Step 4. Read the data in a step

Give the step `reads=["data"]` in `pipeline.py`:

```python
reader = step("read-data", reads=["data"], needs=[hello])
```

In the step's `entry.py`, the dataset is at one place in lakeFS. The platform hands every step the address and keys, so you only build the path:

```python
import argparse
import os

import boto3
import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params)

    repo = cfg["platform"]["lakefs"]["repository"]
    ref = cfg["data"]["ref"]
    version = cfg["data"]["version"] or ref
    prefix = f"{ref}/dataset/{version}/"

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["LAKEFS_ENDPOINT"],
        aws_access_key_id=os.environ["LAKEFS_ACCESS_KEY"],
        aws_secret_access_key=os.environ["LAKEFS_SECRET_KEY"],
    )
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=repo, Prefix=prefix):
        for obj in page.get("Contents", []):
            print(obj["Key"])
            # s3.download_file(repo, obj["Key"], "/tmp/" + obj["Key"].split("/")[-1])


if __name__ == "__main__":
    main()
```

Add `boto3` to that step's Dockerfile: `RUN pip install --no-cache-dir PyYAML boto3`.

Send the change in as usual ([Send your change in](send-it-in.md)). When you run, set `data-ref` to the name you uploaded with.

## If something goes wrong

- **The browser sign-in fails or never opens.** Copy the link the tool printed into your browser. If it still fails, sign in the guided way with `kubecore-dataset login --paste`, then run the upload again.
- **`externally-managed-environment`.** Install inside the virtual environment, as in Step 1.
- **The step lists no files.** Check `data-ref` on the run page is the name you uploaded with (`main` if you gave none), and `data-version` is empty.
