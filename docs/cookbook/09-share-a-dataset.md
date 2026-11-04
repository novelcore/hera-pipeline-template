# 9. Share a dataset with another project

Another project of your organisation can let your project **read** one of its datasets. You never get write access to it.

## Do this

1. Ask the owning project to share the dataset with your project. They do it from their side; you cannot share someone else's data yourself.
2. List what is shared with you:

```bash
kaosctl dataset list --shared
kaosctl dataset versions team-a/dataset-cats
```

3. Use it by putting the owner's project name in front, on the laptop or in the run form's **dataset** field:

```bash
kaosctl dataset pull team-a/dataset-cats@v3
```

```python
ref = datasets.DatasetRef.parse("team-a/dataset-cats@v3")
```

The step needs `kaos-lib[zitadel]` (as in [step 6](06-change-a-step.md)) so it can prove who it is to the other project.

## You should now see

- The shared dataset and its versions in `kaosctl dataset list --shared`.
- A read-only copy after `pull`.

Trying to release, push to or create a shared dataset fails, by design:

```text
ERROR: cannot release team-a/dataset-x: it belongs to project team-a, and datasets shared with your project are read-only. Ask team-a to release it.
```

Next: [when things go wrong](10-when-things-go-wrong.md).
