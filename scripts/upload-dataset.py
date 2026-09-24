#!/usr/bin/env python3
"""Upload a local dataset to your app's lakeFS.

    ./scripts/upload-dataset.py <local-dataset-dir> [dataset-name]

  <local-dataset-dir>  Folder whose contents become the dataset (what your
                       steps read from s3://<repo>/<name>/dataset/<version>/).
  dataset-name         What you will type as `data-ref` when you run the
                       pipeline. Default: `main`. Use a new name for a new
                       dataset; re-using a name REPLACES that dataset's
                       contents with your folder (you are asked first if
                       anything would be deleted).

The files land at the path the pipeline reads:

    s3://<repo>/<dataset-name>/dataset/<data-version>/

where data-version defaults to the dataset name (--data-version to change it).
lakeFS URL + repo are read from .kubecore/dataset-config.yaml when it exists;
otherwise pass --url and --repo.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

# Make the vendored dataset_tools importable whether run from the repo root or
# elsewhere.
_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "dataset_tools"))

from dataset_cli.appconfig import config_value  # noqa: E402
from dataset_cli.lakefs_client import LakeFSClient  # noqa: E402
from dataset_cli.login import login as do_login  # noqa: E402
from dataset_cli.sync import dataset_prefix, sync as do_sync  # noqa: E402
from dataset_cli.validate import validate_dataset  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload a dataset to lakeFS, where the pipeline reads it.")
    ap.add_argument("dataset_dir", help="local dataset folder; its contents become the dataset")
    ap.add_argument("name", nargs="?", default=None,
                    help="dataset name = the data-ref you type when running (default: main)")
    ap.add_argument("--branch", default=None, help=argparse.SUPPRESS)  # old spelling of `name`
    ap.add_argument("--data-version", default=None,
                    help="data-version folder inside the dataset (default: same as the name)")
    ap.add_argument("--url", default=None, help="lakeFS ingress URL (default: .kubecore/dataset-config.yaml)")
    ap.add_argument("--repo", default=None, help="lakeFS repo (default: .kubecore/dataset-config.yaml)")
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--prefix", default=None,
                    help="advanced: override the standard dataset/<data-version> location")
    ap.add_argument("--yes", action="store_true",
                    help="don't ask before deleting remote files that are not in your folder")
    ap.add_argument("--dry-run", action="store_true", help="show what would sync, upload nothing")
    args = ap.parse_args()

    if args.name and args.branch and args.name != args.branch:
        sys.exit(f"ERROR: dataset name '{args.name}' and --branch '{args.branch}' disagree; pass one.")

    start = args.dataset_dir
    url = args.url or config_value("lakefsUrl", start)
    repo = args.repo or config_value("repo", start)
    branch = args.name or args.branch or config_value("branch", start) or "main"
    version = args.data_version or branch
    prefix = args.prefix.strip("/") if args.prefix else dataset_prefix(version)

    if not url or not repo:
        sys.exit("ERROR: could not determine lakeFS url/repo. Run inside the app "
                 "clone (it ships .kubecore/dataset-config.yaml), or pass --url/--repo.")

    # 1) validate locally before touching the network
    result = validate_dataset(args.dataset_dir)
    if not result.ok:
        print("✗ Dataset invalid — fix these before uploading:")
        for e in result.errors:
            print(f"    - {e}")
        return 2
    print("✓ Dataset valid.")
    print(f"  Dataset name (data-ref): {branch}   data-version: {version}")
    print(f"  Target: s3://{repo}/{branch}/{prefix}/")

    if args.dry_run:
        print("(--dry-run) skipping login + upload.")
        return 0

    # 2) browser login -> per-user bearer token (cookie paste only as fallback)
    cred = do_login(url)
    client = LakeFSClient(url, cookie=cred.cookie, token=cred.token,
                          concurrency=args.concurrency)
    if not client.branch_exists(repo, branch):
        client.ensure_branch(repo, branch, client.default_branch(repo))

    # 3) incremental sync (uploads + deletions, deletions confirmed), then commit
    commit_id = do_sync(pathlib.Path(args.dataset_dir), client, repo, branch,
                        prefix=prefix, concurrency=args.concurrency,
                        extra_metadata={"branch": branch, "data_version": version},
                        confirm_deletes=not args.yes)
    print(f"\n✓ Uploaded to s3://{repo}/{branch}/{prefix}/  (commit {commit_id})")
    print(f"  When you run the pipeline, set data-ref = {branch}"
          + (f" and data-version = {version}" if version != branch else "") + ".")
    return 0


if __name__ == "__main__":
    import requests

    from dataset_cli.__main__ import unreachable_message  # noqa: E402

    try:
        sys.exit(main())
    except requests.exceptions.ConnectionError as exc:
        sys.exit(unreachable_message(exc))
