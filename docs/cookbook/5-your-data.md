# 5. Your data

**Goal:** a dataset with your files in it, released as `v1`, and shared with another project if
that project needs it.

**Who can do it:** creating, uploading and releasing need access to your project's lakeFS; any
`dev`, `ops` or `admin` of the project works. Sharing with another project is for the **admins of
the owning project** only.

A dataset is a lakeFS repository named `dataset-<name>`. Versions are tags `v1`, `v2`, … on `main`,
and every change reaches `main` through a pull request. [Datasets](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/datasets.html), in the kaos-lib
guide, covers this in more detail.

## 1. Create it

```bash
kaosctl dataset create cats --layout yolo --classes cat,kitten   # yolo layout: images, labels, data.yaml
kaosctl dataset create notes                                     # no layout: empty, takes any files
```

A new dataset has no layout unless you pick one: `--layout yolo` (or any layout from
`kaosctl layout list`), or `--layout none` to say so.

Or in the browser: lakeFS → **Datasets** → **New dataset** (name, description, layout, classes).
**No layout** is chosen until you pick one.
Details: [Datasets, in the browser](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/datasets.html#in-the-browser).

**You should see** `dataset-cats` with `data.yaml`, `images/{train,val,test}/` and
`labels/{train,val,test}/` on `main`.

## 2. Upload your files

=== "yolo images and labels"

    ```bash
    kaosctl dataset pull dataset-cats@latest ./dataset-cats
    cp ~/my-images/train/*.jpg  ./dataset-cats/images/train/
    cp ~/my-labels/train/*.txt  ./dataset-cats/labels/train/     # one .txt per image, same file name
    cp ~/my-images/val/*.jpg    ./dataset-cats/images/val/
    cp ~/my-labels/val/*.txt    ./dataset-cats/labels/val/
    kaosctl dataset push ./dataset-cats dataset-cats -m "first 200 images"
    ```

    The step by step version, with the label format, is in
    [Prepare and upload a yolo dataset](https://github.com/novelcore/yolo-pipelines-template/blob/dev/docs/prepare-dataset.md), in the yolo guide.

=== "any files (raw)"

    ```bash
    kaosctl dataset push ./my-folder dataset-notes -m "first export"
    ```

    A dataset with layout `none` takes the files as they are.

`push` makes the dataset look exactly like your folder. It checks the folder first, uploads to a
draft branch, and **opens a pull request**. It prints the link. In the browser you can do the same
on a branch: **Branches** → upload → pull request ([in the browser](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/datasets.html#in-the-browser)).

## 3. Validate

`push` validates on its own. To check a folder before you push:

```bash
kaosctl dataset validate ./dataset-cats            # exit code 0 ok, 2 the dataset is invalid
```

Every problem is listed: a label without an image, a class id outside `names`, and so on
([layouts and what they check](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/datasets.html#layouts)).

## 4. Merge the pull request

Open the link `push` printed, look at the change in lakeFS, and **Merge** it into `main`. Until you
merge, `main` is unchanged.

## 5. Release v1

In lakeFS, open the dataset and click **Release version**. From a terminal:

```bash
kaosctl dataset release dataset-cats      # prints v1
kaosctl dataset versions dataset-cats
```

**You should see**, a few minutes later, `dataset-cats@v1` in your pipeline's `dataset` dropdown
([Quickstart: release a version](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/quickstart.html#4-release-a-version)).

## 6. Share it with another project

The owner project's admin does this in the console: **Datasets** → the dataset → **Sharing** tab →
*Share with project* → **Add a project…** → **Save sharing**. The other project can then read it,
but never write it ([Share a dataset](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/shared-datasets.html#share-a-dataset-the-owning-project)).

## 7. Use a dataset another project shared with you

```bash
kaosctl dataset list --shared
kaosctl dataset pull team-a/dataset-cats@v3 ./cats
```

On your run form it appears as `team-a/dataset-cats@v3`. The owner project's name comes first.

## If it isn't there

| symptom | fix |
|---|---|
| `push` stops with a list of problems | fix each one; it lists them all at once ([layouts](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/datasets.html#layouts)) |
| `push` says the folder is not a yolo dataset, but you meant raw files | create the dataset with `--layout none`, or push with `--no-validate` |
| the new version is not in the run form's dropdown | wait a few minutes and reopen the form; the list is refreshed after each release |
| a shared dataset is not in your dropdown | the owner has not saved the sharing yet, or your pipeline has not been refreshed; a release of any dataset in your project refreshes it |
| `create` or `push` refused on a shared dataset | it belongs to the other project; only the owner writes it |

**Next:** [6. Your pipeline](6-your-pipeline.md).
