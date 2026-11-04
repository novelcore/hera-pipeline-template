# dataset_tools (retired)

This folder holds the old `kubecore-dataset` tool, which stored a dataset as a branch. It is
**no longer the way to work with data** and its guide has been removed.

Use `kaosctl` from the `kaos-lib` package instead. A dataset is now its own repository with
numbered versions:

- [Install kaosctl](../docs/cookbook/03-install-kaosctl.md)
- [Create a dataset, upload data, release v1](../docs/cookbook/04-create-a-dataset.md)
- [Use it in a step](../docs/cookbook/06-change-a-step.md)
