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
              LAKEFS_DATA_VERSION (optional; default = LAKEFS_BRANCH),
              UPLOAD_PREFIX (optional; overrides the standard dataset/<version>).
"""
from __future__ import annotations

import os
import pathlib
import sys

from dataset_cli.lakefs_client import LakeFSClient
from dataset_cli.login import Credential, login as do_login, save_session
from dataset_cli.sync import dataset_prefix, sync as do_sync


def main() -> None:
    url = os.environ.get("LAKEFS_URL")
    repo = os.environ.get("LAKEFS_REPO")
    branch = os.environ.get("LAKEFS_BRANCH", "main")
    local = os.environ.get("LOCAL_DIR")
    if not (url and repo and local):
        sys.exit("ERROR: LAKEFS_URL, LAKEFS_REPO and LOCAL_DIR are required.")
    concurrency = int(os.environ.get("CONCURRENCY", "16"))
    # Platform standard: <branch>/dataset/<data-version>/, the path the pipeline
    # reads. UPLOAD_PREFIX still overrides it for the rare custom layout.
    version = os.environ.get("LAKEFS_DATA_VERSION") or branch
    prefix = os.environ.get("UPLOAD_PREFIX", "").strip("/") or dataset_prefix(version)

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
    if not client.branch_exists(repo, branch):
        client.ensure_branch(repo, branch, client.default_branch(repo))

    do_sync(pathlib.Path(local), client, repo, branch,
            prefix=prefix, concurrency=concurrency)


if __name__ == "__main__":
    main()
