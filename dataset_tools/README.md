# `kubecore-dataset`: the upload tool

Gets a folder of data from your laptop into your project's lakeFS, at the place the
pipeline reads it. Sign-in is your normal browser login: no keys, no cluster access.

```bash
pip install ./dataset_tools                                   # once, from the repo root
./scripts/upload-dataset.py  /path/to/your-data  my-first-dataset
```

That signs you in, checks the folder, uploads it as the dataset **`my-first-dataset`**
and saves a version. The name is the **data-ref**; leave it out and it is `main`. The
data lands at:

```
s3://<repo>/<data-ref>/dataset/<data-version>/      # data-version defaults to the name
```

**One name = one dataset.** Uploading to a name that already has a dataset makes it
match your folder: files you don't have locally are removed. The tool lists them and
asks first (`--yes` skips the question). Use a new name to keep both.

The lakeFS link and repo come from `.kubecore/dataset-config.yaml` (the platform writes
it; `.kubecore/dataset-config.yaml.example` shows the fields). Otherwise pass `--url`
and `--repo`.

## Subcommands

```bash
kubecore-dataset login                                  # browser sign-in, cached
kubecore-dataset validate /path/to/your-data            # the pre-upload check
kubecore-dataset sync /path/to/your-data --branch NAME  # same upload, flag form
```

If `kubecore-dataset` is "not found", use `python -m dataset_cli <command>`.

## Checking your data format

This template has no fixed data format, so `validate` only checks that the folder
exists and has files. Add your format's checks to `check_format` in
`dataset_cli/validate.py`: anything appended to `errors` stops the upload.

## Options

| Flag | What it is |
|---|---|
| 2nd argument / `--branch` | the dataset name, i.e. the data-ref |
| `--data-version` | a version folder inside the dataset (default: the name) |
| `--yes` | don't ask before removing files that aren't in your folder |
| `--url`, `--repo` | lakeFS link and repo, if there is no config file |
| `--paste` | manual sign-in instead of the browser login |
| `--dry-run` | show what would change, upload nothing |
