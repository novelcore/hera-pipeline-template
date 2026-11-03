# Share a dataset

**Goal:** another project of your organisation can **read** one of your datasets (never write it).
Models are not shared.

## Share it (the owner)

**Who:** the admins of the project that owns the dataset. Everyone else sees the list but cannot
change it.

1. Open the KAOS console → **Datasets** → your dataset.
2. Open the **Sharing** tab, choose **Share with project** → **Add a project…**, and **Save sharing**.

lakeFS shows who a dataset is shared with on its page. Removing a project from the list stops its
reads within a couple of minutes.

## Use it (the other project)

A shared dataset is named with its owner project: `<owner-project>/dataset-<name>@<version>`.

```bash
kaosctl dataset list --shared                      # what other projects share with yours
kaosctl dataset versions team-a/dataset-cats
kaosctl dataset pull team-a/dataset-cats@v3 ./cats
```

- **In a pipeline**, the run form's `dataset` dropdown offers it as `team-a/dataset-cats@v3` once your
  pipeline has been refreshed (any release of a dataset in your project refreshes it).
- **In a step**, `datasets.materialize("team-a/dataset-cats@v3")` reads it like your own.
- `create`, `push` and `release` of a shared dataset are refused: it stays the owner's.

**Next:** [Use a dataset in a step](dataset-in-a-step.md).
