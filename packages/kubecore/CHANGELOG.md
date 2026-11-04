# kaos-lib changelog (formerly the kubecore package)

One `## <version>` section per release, newest first. When the platform moves an app to a
version outside the app's `.kaos/compat.yaml` range, its bump pull request carries that
version's section (docs/kaos-lib-versions.md in the templates). A release that needs a
change in app code says what to change under **Migration**.

## 0.2.0

- Datasets are lakeFS repositories (`dataset-<name>`); `DatasetRef.parse` accepts any
  repository and a ref that is `vN`, `latest`, a branch, a tag or a commit id.
- `datasets.materialize` picks the format from the repository's `kaos.template` label
  (`ultralytics`, or `raw` for an unlabelled repository).
- Datasets other projects share with yours (the `zitadel` extra mints the step's token).
- `outputs.run`: one merge commit on `main` per step per run; a retry resumes.
- The `kubecore` CLI: `login`, `dataset create | pull | validate | push | release | list | versions`.
