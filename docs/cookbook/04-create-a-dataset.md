# 4. Create a dataset, upload data, release v1

A dataset is its own lakeFS repository called `dataset-<name>`. Its versions are `v1`, `v2`, ... A new dataset has **no layout** unless you ask for one. A layout says what files the dataset holds and what is checked when you upload. Two are built in: `yolo` (images plus YOLO label files) and `raw` (any files, nothing checked). Run `kaosctl layout list` to see them.

## Do this

**1. Create it.** For yolo-shaped data:

```bash
kaosctl dataset create cats --layout yolo --classes cat,kitten
```

For any other data, leave the layout out: `kaosctl dataset create cats`. That makes an empty dataset that accepts any files. (`--classes` and `--param` without a layout is an error.)

**2. Put your files in.**

```bash
kaosctl dataset pull dataset-cats@latest ./dataset-cats
# copy your images into ./dataset-cats/images/train and images/val,
# and one label file per image into ./dataset-cats/labels/train and labels/val
kaosctl dataset validate ./dataset-cats
kaosctl dataset push ./dataset-cats dataset-cats -m "first 200 images"
```

`validate` lists every problem it finds, so fix those before you push. `push` checks again, uploads, and opens a **pull request**: a proposed change that goes into the dataset only once someone accepts it.

**3. Accept the change.** On **Datasets**, click your dataset, then **Open in lakeFS**, open the pull request and merge it.

**4. Release v1.** Either on the dataset's page in the console click **Release v1**, or:

```bash
kaosctl dataset release dataset-cats
kaosctl dataset versions dataset-cats
```

## You should now see

- After `create`: the link to the new dataset, and `dataset-cats` on the **Datasets** page.
- After `push`: the link to the pull request.
- After release: `kaosctl dataset versions dataset-cats` lists `v1`.
- Within about a minute `dataset-cats@v1` shows up in the **dataset** dropdown of the run form ([step 7](07-run-it.md)), newest version first, then `@latest`.

!!! note "Why versions?"
    A run reads one version, so a result always points back to the exact data it used. `@latest` means "whatever is newest right now" and can change between runs; use `@v1` when you want repeatable results.

Next: [create your pipeline](05-create-your-pipeline.md).
