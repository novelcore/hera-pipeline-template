# Upload your data

Your pipeline reads its data from your project's data store, called lakeFS. This page puts a folder from your computer there. You only need your browser to sign in. No keys and no cluster access.

## Step 1. Install the upload tool

Run this once, from the top folder of your project.

```bash
pip install ./dataset_tools
```

## Step 2. Tell the tool where your data store is

The platform usually writes this for you, in `.kubecore/dataset-config.yaml`. If that file is missing, copy the example and fill in the two links your Novelcore contact gives you.

```bash
cp .kubecore/dataset-config.yaml.example .kubecore/dataset-config.yaml
```

Or skip the file and add `--url <your-lakefs-link> --repo <your-repo-name>` to the command in the next step.

## Step 3. Upload

Point the tool at your folder and give the dataset a name.

```bash
python3 scripts/upload-dataset.py /path/to/your-data my-first-dataset
```

Leave the name out and it is called `main`. The first time, your browser opens the normal sign-in page. Sign in, then go back to the terminal. The tool checks the folder, uploads it, and saves a version.

!!! warning "Same name replaces"
    Uploading again with a name you already used makes that dataset match your folder. Files you do not have on your computer are removed from it. The tool shows you which files and asks before it removes anything. To keep the old one, pick a new name.

## Step 4. Remember the name

The tool finishes by telling you the dataset name. That name is the **data ref**. Your steps find the data at this address, where `<data-version>` is the same as the name unless you chose otherwise:

```
s3://<repo>/<data-ref>/dataset/<data-version>/
```

## For developers: check your format before upload

The tool only checks that the folder is there and has files. To catch format mistakes on the laptop instead of in a failed run, add your checks to `check_format` in `dataset_tools/dataset_cli/validate.py`.
