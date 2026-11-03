# Release a version

**Goal:** a version (`v1`, `v2`, …) that pipelines can pick. A version is a tag on `main`; it never
changes.

**You need:** your data merged into `main` ([Add data](dataset-upload.md)).

## Do it

In the browser: open the dataset on lakeFS's **Datasets** page and click **Release version**.

From a terminal:

```bash
kaosctl dataset release dataset-cats      # prints v1, then v2 next time, ...
kaosctl dataset versions dataset-cats     # every version, newest first
```

## What you should see

A few minutes later the run form's **`dataset`** dropdown offers it:

```
dataset-cats@v1
dataset-cats@latest
dataset-default@latest
```

The dropdown is refreshed when a dataset or a version changes. If the new version is not there yet,
wait a few minutes and open the form again.

**Next:** [run your pipeline on it](run-it.md).
