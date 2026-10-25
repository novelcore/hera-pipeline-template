#!/usr/bin/env python3
"""DEPRECATED shim — kept for back-compat with the old env-var interface.

The real tool is now the ``kubecore-dataset`` CLI (package ``dataset_cli``),
which adds a browser login (no cookie copy-paste), dataset validation, and a
true incremental sync (uploads AND deletions). Prefer:

    kubecore-dataset sync <dir> --url $LAKEFS_URL --repo $LAKEFS_REPO --branch $LAKEFS_BRANCH

This shim maps the old env vars onto the new `sync` command so existing scripts
keep working. It reuses the cached browser session if present; if a
``LAKEFS_COOKIE`` is provided it is used directly (old behaviour).

Old env vars: LAKEFS_URL, LAKEFS_REPO, LAKEFS_BRANCH, LOCAL_DIR,
              LAKEFS_COOKIE (optional), CONCURRENCY (optional),
              UPLOAD_PREFIX (optional; overrides the standard dataset/),
              LAKEFS_SYNC_YES=1 (optional; delete remote files that are not in
              LOCAL_DIR without asking — otherwise you are asked first).
LAKEFS_DATA_VERSION was removed: a dataset lives at <branch>/dataset/.
"""
from __future__ import annotations

import os
import pathlib
import sys

from dataset_cli.lakefs_client import LakeFSClient
from dataset_cli.login import Credential, login as do_login, save_session
from dataset_cli.sync import branch_source, check_branch_name, dataset_prefix, sync as do_sync


def main() -> None:
    url = os.environ.get("LAKEFS_URL")
    repo = os.environ.get("LAKEFS_REPO")
    branch = os.environ.get("LAKEFS_BRANCH", "main")
    local = os.environ.get("LOCAL_DIR")
    if not (url and repo and local):
        sys.exit("ERROR: LAKEFS_URL, LAKEFS_REPO and LOCAL_DIR are required.")
    concurrency = int(os.environ.get("CONCURRENCY", "16"))
    if os.environ.get("LAKEFS_DATA_VERSION"):
        sys.exit("ERROR: LAKEFS_DATA_VERSION was removed — a dataset now lives at "
                 "<branch>/dataset/. Keep each version on its own LAKEFS_BRANCH.")
    check_branch_name(branch)
    # Platform standard: <branch>/dataset/, the path the pipeline reads.
    # UPLOAD_PREFIX still overrides it for the rare custom layout.
    prefix = os.environ.get("UPLOAD_PREFIX", "").strip("/") or dataset_prefix()

    cookie = os.environ.get("LAKEFS_COOKIE")
    if cookie:
        # honour an explicitly-passed cookie (old behaviour); verify + cache it
        if not LakeFSClient(url, cookie).check_auth():
            sys.exit("ERROR: LAKEFS_COOKIE is invalid or expired.")
        save_session(url, cookie)
        cred = Credential(cookie=cookie)
    else:
        # browser login -> per-user bearer token (cookie paste only as fallback)
        cred = do_login(url)

    client = LakeFSClient(url, cookie=cred.cookie, token=cred.token, concurrency=concurrency)
    created_from = branch_source(client, repo, branch, None)

    do_sync(pathlib.Path(local), client, repo, branch,
            prefix=prefix, concurrency=concurrency,
            confirm_deletes=os.environ.get("LAKEFS_SYNC_YES") != "1",
            created_from=created_from, validated=False)


if __name__ == "__main__":
    main()
