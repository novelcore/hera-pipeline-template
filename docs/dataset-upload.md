# Add or change data

**Goal:** your files in the dataset. Every change goes through a **pull request** into `main`: you
propose it, look at it, and merge it.

**You need:** a dataset ([Create a dataset](dataset-create.md)).

## From a terminal (best for many files)

```bash
kaosctl dataset pull dataset-cats@latest ./dataset-cats       # a copy of what is there
# put your files into ./dataset-cats (for yolo: images/... and one labels/... file per image)
kaosctl dataset validate ./dataset-cats                       # optional: push checks too
kaosctl dataset push ./dataset-cats dataset-cats -m "first 200 images"
```

`push` makes the dataset look exactly like your folder: it uploads new and changed files, removes
files you deleted, and checks the folder against the dataset's layout first. It uploads to a draft
branch and **opens a pull request**, then prints its link. Nothing on `main` changes yet.

- A layout problem stops the push and lists every problem ([Check a dataset](dataset-validate.md)).
  `--no-validate` skips the check and prints a warning.
- `push` into a dataset that does not exist creates it.

## In the browser (best for a few files)

1. In lakeFS, open the dataset → **Branches** → create a branch from `main`.
2. Upload your files to that branch.
3. Open a **pull request** from your branch into `main`.

To change the class names of a yolo dataset, open `data.yaml` and use **Edit** (Edit classes). The
editor writes `data.yaml` again from the names you typed, so its class count always matches, and
saves the change as a pull request.

## Merge it

Open the pull request, look at the change, and **Merge**. Now `main` has your files, and
`dataset-cats@latest` is your data. Pipelines prefer versions, so make one next.

**Next:** [Release a version](dataset-release.md).
