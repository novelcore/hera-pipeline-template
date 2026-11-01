# kubecore

The KAOS platform package: datasets (formats, versions), run outputs, and the `kubecore` CLI, over kaos-lake
(lakeFS). PRD novelcore/kaos#1147 (D-15) and #1283 (D-11, F-14).

## Install

PyPI is not available yet, so install from git, pinned to a commit:

```bash
pip install "git+https://github.com/novelcore/hera-pipeline-template@<sha>#subdirectory=packages/kubecore"
```

Python 3.9+. Dependencies: `requests`, `PyYAML`.

The package and the vendored `kubecore/` engine at the repo root share the import name `kubecore` and must not share a `sys.path`: step images will `pip install` the package from git (pinned to a commit, as above) and will not copy the vendored `kubecore/` into the image; the follow-up conversion removes the vendored copy.

## Data model

- A dataset is its own lakeFS repository `dataset-<name>` (3 to 48 chars of `a-z0-9-` after the prefix);
  each project has `dataset-default`. Versions are tags `v1`, `v2`, ... on `main`; `latest` is the head of
  `main`. A run picks `<dataset-repo>@<version>`.
- Changes reach `main` only through a pull request (the only direct commit is the starter layout written by
  `create`, as the kaos-lake UI does: repo, starter files on main, then labels). New repositories are placed at `<storage_namespace_prefix kaos-lake publishes>/<repo>`, or `$KUBECORE_STORAGE_NAMESPACE_BASE`.
- Each ML app writes results to `outputs-<app>`, on `main`, one commit per run (a merge from the
  run's own branch `run-<run>`, so simultaneous runs never mix), under `checkpoints/<experiment>/<run>/`.

## Python API

```python
from kubecore import datasets, outputs

ref = datasets.DatasetRef.parse("dataset-default@v2")      # DatasetError on malformed input
ref = ref.with_commit(commit)                              # optional: pin the commit dataset-loading resolved
commit = datasets.resolve(ref)                             # pinned commit returned as is, else tag/main head
data_yaml = datasets.materialize(ref, dest=None)           # Path to a data.yaml Ultralytics can train on
datasets.list_datasets(); datasets.versions("dataset-x"); datasets.release("dataset-x")   # -> "vN"

from kubecore.formats import get_format                   # "ultralytics" (alias "yolo"); detect, segment, pose
fmt = get_format("ultralytics")
fmt.creator.skeleton(classes=["cat", "dog"]); fmt.creator.validate(dir); fmt.creator.publish(dir, repo, "msg")
fmt.consumer.materialize(ref, dest, commit=None)

with outputs.run("myapp", "exp1", "run-7", "checkpoints") as r:    # branch run-run-7-checkpoints, reused on retry
    resume = r.latest("weights/")                          # local path of what the branch already holds, or None
    r.save("./ckpt")                                       # upload + commit on the run branch (durable)
    r.finish({"dataset_ref": "dataset-default@v2", "mlflow_run_id": "..."})  # merge into main, delete branch
outputs.write_run("myapp", "exp1", "run-7", "./ckpt")      # shortcut: open, save once, finish
```

An exception inside `with outputs.run(...)` neither merges nor deletes the branch, so the retry resumes.
Leaving the block normally without calling `finish` finishes with no extra metadata. An empty commit or an
empty merge is a success and returns the existing commit.

Datasets are validated for detection (`cls x y w h`), segmentation (`cls x1 y1 x2 y2 ...`, even count >= 6) and
pose (`kpt_shape: [K, D]`, K*D values per line, visibility 0/1/2 when D=3). `nc` is optional when `names` is given.

### Rights each call needs

| call | needs |
| --- | --- |
| `resolve`, `materialize`, `consumer.materialize`, `versions`, `list_datasets`, `DatasetRef` | read on `dataset-*` (an app key can) |
| `outputs.run(...)` / `write_run` (`open`, `save`, `latest`, `finish`) | write on that app's `outputs-<app>` (an app key can) |
| `release` | tag creation on the dataset: people or admins, not an app key |
| `create_dataset`, `creator.publish` / `publish_tree` (repository, draft branch, pull request) | people or admins, not an app key |

`materialize` downloads only `data.yaml`, `images/`, `labels/` at the pinned commit, rewrites `path:`, and
caches by (repo, commit) (`$KUBECORE_CACHE_DIR`, default `~/.cache/kubecore/datasets`); a second call is
free. If `$KUBECORE_STAGED_DIR` holds that commit (MeluXina staging), it is used in place and nothing is
downloaded.

## Credentials (one chain, no secrets in the package)

1. `LAKEFS_ACCESS_KEY` + `LAKEFS_SECRET_KEY` (an app's key pair), endpoint `LAKEFS_ENDPOINT`
2. `LAKEFS_BEARER_TOKEN` (MeluXina jobs)
3. the browser login session of `kubecore login` (a person's Zitadel token), cached in
   `~/.config/kubecore-ml/lakefs-session.json`

The lakeFS URL comes from `--url`, `LAKEFS_ENDPOINT`/`LAKEFS_URL`, or `.kubecore/dataset-config.yaml`
(written into every app repo by the platform, which also carries the login settings).

## CLI

```
kubecore login
kubecore dataset create <name> --classes a,b,c [--description ...]
kubecore dataset list
kubecore dataset versions <repo>
kubecore dataset release <repo>
kubecore dataset push <dir> <repo> -m "message" [--no-validate]   # validates, draft branch, pull request
kubecore dataset pull <repo>@<version> [dest]
kubecore dataset validate <dir>
```

Every command prints the next step and the lakeFS link (dataset page, pull request, version).
Exit codes: 0 ok, 1 user error (one `ERROR:` line), 2 invalid dataset.

## Tests

```bash
cd packages/kubecore && pip install -e ".[test]" && pytest
```

A fake lakeFS (`tests/fake_lakefs.py`) runs the real client over an in-memory transport; no network.

## File map

| file | job |
| --- | --- |
| `config.py` | per-app config discovery, lakeFS URL, OIDC settings |
| `credentials.py` | the credential chain, session cache, browser login |
| `oidc.py` | PKCE browser login to Zitadel (ported from `dataset_tools`) |
| `lakefs.py` | lakeFS REST client |
| `transfer.py` | mirror plan, upload, download of file trees |
| `datasets.py` | refs, resolve, list, versions, release, create, publish via PR, materialize |
| `formats/` | format registry; `ultralytics.py` creator + consumer |
| `outputs.py` | `outputs-<app>` writes |
| `cli.py` | the `kubecore` command |
