# Create a dataset

**Goal:** a new dataset `dataset-<name>`, ready for your files.

**You need:** [kaosctl installed and signed in](cookbook/4-install-kaosctl.md), or a browser.

A name is `dataset-` followed by 3 to 48 lowercase letters, digits or hyphens. You only type the part
after `dataset-`.

## In the browser

1. Open your project's lakeFS and go to **Datasets**. (From the KAOS console: **Datasets** →
   **Create in project**, which opens that project's lakeFS.)
2. Click **New dataset**.
3. Type the name and a short description, and pick a layout:
    - **yolo**: images and YOLO labels, with a `data.yaml` that names the classes. Type the class
      names, one per line, in label-id order (the first one is id `0`).
    - **none**: an empty dataset that takes any files.
4. Create it. The page shows what to do next.

## From a terminal

```bash
kaosctl dataset create cats --classes cat,kitten     # yolo layout (the default)
kaosctl dataset create notes --layout none           # empty, any files
kaosctl dataset create cats --classes cat,kitten --description "street cats, 2026"
```

The command prints the link to the new dataset.

## What you should see

`dataset-cats` with a starter layout on `main`:

```
data.yaml          path, train/val/test folders, names (your classes)
images/train/      images/val/      images/test/
labels/train/      labels/val/      labels/test/
README.md
```

A layout is optional: `--layout none` makes an empty dataset, and a repository named
`dataset-<something>` that you create by hand in lakeFS becomes a dataset after its first commit.

**Next:** [Add data](dataset-upload.md).
