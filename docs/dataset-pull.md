# Download a dataset

**Goal:** a dataset version, or one folder of it, on your computer.

```bash
kaosctl dataset pull dataset-cats@v1 ./cats-v1                 # a version into a folder
kaosctl dataset pull dataset-cats@latest                       # into a per-commit cache, prints where
kaosctl dataset pull outputs-<app>@main ./run --prefix checkpoints/<experiment>/<run>/   # one folder
```

A ref can be a version (`v1`), `latest`, a branch, a tag or a commit id. The copy is kept by
repository and commit, so pulling the same commit again is instant.

A copy you pulled is yours to change. To send the changes back, [push](dataset-upload.md) the
folder: that opens a pull request.

**Next:** [Use a dataset in a step](dataset-in-a-step.md).
