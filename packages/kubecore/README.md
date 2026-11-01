# kubecore

The KAOS platform package: datasets (formats, versions), run outputs, and the `kubecore` CLI, over kaos-lake
(lakeFS). PRD novelcore/kaos#1147 (D-15) and #1283 (D-11, F-14).

## Install

PyPI is not available yet, so install from git, pinned to a commit:

```bash
pip install "git+https://github.com/novelcore/hera-pipeline-template@<sha>#subdirectory=packages/kubecore"
```

Python 3.9+. Dependencies: `requests`, `PyYAML`. Note: this repo's root also holds the vendored engine
`kubecore/` (a different thing with the same import name). Do not put the repo root on `sys.path` in the
same environment as this package; a follow-up converts the templates onto the package and removes the copy.

## Data model

- A dataset is its own lakeFS repository `dataset-<name>` (3 to 48 chars of `a-z0-9-` after the prefix);
  each project has `dataset-default`. Versions are tags `v1`, `v2`, ... on `main`; `latest` is the head of
  `main`. A run picks `<dataset-repo>@<version>`.
- Changes reach `main` only through a pull request (the only direct commit is the starter layout written by
  `create`, as kaos-lake does).
- Each ML app writes results to `outputs-<app>`, on `main`, one commit per run, under
  `checkpoints/<experiment>/<run>/`.

## Python API

```python
from kubecore import datasets, outputs

ref = datasets.DatasetRef.parse("dataset-default@v2")      # DatasetError on malformed input
commit = datasets.resolve(ref)                             # lakeFS commit id
data_yaml = datasets.materialize(ref, dest=None)           # Path to a data.yaml Ultralytics can train on
datasets.list_datasets(); datasets.versions("dataset-x"); datasets.release("dataset-x")   # -> "vN"

from kubecore.formats import get_format                   # "ultralytics" (alias "yolo")
fmt = get_format("ultralytics")
fmt.creator.skeleton(classes=["cat", "dog"]); fmt.creator.validate(dir); fmt.creator.publish(dir, repo, "msg")
fmt.consumer.materialize(ref, dest)

outputs.write_run("myapp", "exp1", "run-7", "./ckpt")      # one commit on outputs-myapp main
```

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
kubecore dataset push <dir> <repo> -m "message"      # validates, draft branch, pull request
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
