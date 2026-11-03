# What a dataset is

A dataset is a **lakeFS repository** named `dataset-<name>`. Every project starts with one,
`dataset-default`, which is empty until you put files in it. lakeFS is the data store of your
project; it keeps every version of every file, like Git does for code.

| word | what it means |
|---|---|
| **version** | a tag on `main`: `v1`, `v2`, … You make one with **Release version**. |
| **`latest`** | the newest data on `main`, whatever it is right now. |
| **change** | a **pull request** into `main`. Nothing lands on `main` until a person merges it. |
| **pick** | `<repository>@<version>`, for example `dataset-cats@v1`. The run form's `dataset` field is a dropdown of these. |
| **layout** | the shape a dataset must have, for example `yolo` (images and labels). It decides what `validate` checks. A dataset can have no layout. |
| **results** | never written into a dataset. A pipeline writes to your app's own repository, `outputs-<app>` ([Results](results.md)). |

A run reads **one commit**: the one its pick resolves to when the run starts. Merging new data
while a run is going does not change what that run reads, so every result points back to the exact
data it came from.

## Where you work with datasets

| place | what you do there |
|---|---|
| **The KAOS console**, Datasets page | see every dataset of your organisation, its versions and its location; share a dataset with another project; open a project's lakeFS to create one. |
| **lakeFS** (your project's data store), Datasets page | **New dataset**, upload files on a branch, open and merge pull requests, edit `data.yaml`, **Release version**. |
| **`kaosctl`** on your computer | the same from a terminal: create, push a folder, validate, release, download. [Install it](cookbook/4-install-kaosctl.md). |
| **A pipeline step** | read the version the run picked, with kaos-lib ([Use a dataset in a step](dataset-in-a-step.md)). |

## The tasks

1. [Install kaosctl and sign in](cookbook/4-install-kaosctl.md) (once per computer).
2. [Create a dataset](dataset-create.md).
3. [Add or change data](dataset-upload.md), always through a pull request.
4. [Check a dataset](dataset-validate.md) before you push it.
5. [Release a version](dataset-release.md) so pipelines can pick it.
6. [Download a dataset](dataset-pull.md) to work on it.
7. [Share a dataset](dataset-share.md) with another project.
8. [Use a dataset in a step](dataset-in-a-step.md).

!!! note "Who may do what"
    People create datasets, push changes, merge pull requests and release versions. A pipeline only
    **reads** datasets: no step can write to a dataset, and nobody can write to a dataset's `main`
    directly.
