"""kubecore-dataset CLI entrypoint.

Subcommands:
  login     Log in to lakeFS via the browser (Zitadel PKCE login, paste fallback).
  validate  Check a local dataset against the Ultralytics-pose contract.
  sync      Validate, then incrementally sync (adds+deletes) to a lakeFS branch.
  upload    Same as `sync` (the old one-liner's name).
  list      Show the datasets in the repository (branches and tags holding one).

Config precedence for every value: CLI flag > environment variable > default.
  LAKEFS_URL     external ingress, e.g. https://lakefs-<project>.<baseDns> (auto-discovered from .kubecore/dataset-config.yaml)
  LAKEFS_REPO    lakeFS repository (default: derived / required)
  LAKEFS_BRANCH  target branch (default: main)
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

import requests

from . import __version__
from .appconfig import config_value
from .lakefs_client import LakeFSClient
from .login import login as do_login
from .sync import RESERVED_BRANCHES, check_branch_name, dataset_prefix, open_branch, sync as do_sync
from .validate import validate_dataset


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _dataset_start(args) -> str | None:
    # anchor for config discovery: the dataset dir if given, else CWD
    return getattr(args, "dataset_dir", None)


def _resolve_url(args) -> str:
    # precedence: flag > env > per-app .kubecore/dataset-config.yaml (nothing hardcoded)
    url = args.url or _env("LAKEFS_URL") or config_value("lakefsUrl", _dataset_start(args))
    if not url:
        sys.exit(
            "ERROR: could not determine the lakeFS URL. Run inside your app clone "
            "(which carries .kubecore/dataset-config.yaml), or pass --url / set "
            "LAKEFS_URL (e.g. https://lakefs-<project>.<baseDns>)."
        )
    return url.rstrip("/")


def _resolve_repo(args) -> str:
    repo = args.repo or _env("LAKEFS_REPO") or config_value("repo", _dataset_start(args))
    if not repo:
        sys.exit(
            "ERROR: could not determine the lakeFS repo. Run inside your app clone, "
            "or pass --repo / set LAKEFS_REPO."
        )
    return repo


def cmd_login(args) -> int:
    url = _resolve_url(args)
    do_login(url, force=args.force, prefer_paste=args.paste)
    return 0


def cmd_validate(args) -> int:
    result = validate_dataset(args.dataset_dir)
    print(result.report())
    return 0 if result.ok else 2


def cmd_sync(args, *, do_auth: bool = True) -> int:
    url = _resolve_url(args)
    repo = _resolve_repo(args)
    branch = args.branch or _env("LAKEFS_BRANCH", "main")
    root = pathlib.Path(args.dataset_dir)
    if args.data_version:
        sys.exit("ERROR: --data-version was removed — a dataset now lives at "
                 "<branch>/dataset/. Keep each version on its own branch (--branch).")
    check_branch_name(branch)

    prefix = (args.prefix or "").strip("/") or dataset_prefix()
    print(f"Dataset name (data-ref): {branch}")
    print(f"Target: s3://{repo}/{branch}/{prefix}/\n")

    # 1) validate (unless skipped)
    validated = not args.skip_validation
    if validated:
        result = validate_dataset(root)
        print(result.report())
        if not result.ok:
            sys.exit("Aborting: dataset failed validation. Fix the errors above, "
                     "or re-run with --skip-validation to force.")

    # 2) auth
    cred = do_login(url, prefer_paste=args.paste) if do_auth else do_login(url)
    client = LakeFSClient(url, cookie=cred.cookie, token=cred.token,
                          concurrency=args.concurrency)

    # 3) ensure branch exists (a new one starts as a copy of --from / the default branch)
    created_from = open_branch(client, repo, branch, args.source, dry_run=args.dry_run)

    # 4) incremental sync + commit
    commit_id = do_sync(
        root, client, repo, branch,
        prefix=prefix, concurrency=args.concurrency, dry_run=args.dry_run,
        extra_metadata={"branch": branch},
        confirm_deletes=not args.yes, remove_legacy=args.remove_legacy,
        created_from=created_from, validated=validated,
    )
    if commit_id and not args.dry_run:
        # No cluster/kubectl instructions here: the client has only the browser
        # and the run form.
        print(f"\n✓ Done. Dataset '{branch}' is uploaded and versioned (commit {commit_id[:12]}).")
        print(f"  When you run the pipeline, set data-ref = {branch}.")
    return 0


def cmd_list(args) -> int:
    """Datasets = branches and tags holding dataset/data.yaml (or the old
    dataset/<ref>/data.yaml layout). Tags are frozen; branches move."""
    url = _resolve_url(args)
    repo = _resolve_repo(args)
    cred = do_login(url, prefer_paste=args.paste)
    client = LakeFSClient(url, cookie=cred.cookie, token=cred.token)
    rows = []
    for kind in ("branches", "tags"):
        for ref in client.list_refs(repo, kind):
            name = ref.get("id", "")
            if not name or name in RESERVED_BRANCHES:
                continue
            if client.object_exists(repo, name, f"{dataset_prefix()}/data.yaml"):
                layout = f"{dataset_prefix()}/"
            elif client.object_exists(repo, name, f"{dataset_prefix()}/{name}/data.yaml"):
                layout = f"{dataset_prefix()}/{name}/ (old layout)"
            else:
                continue
            rows.append((name, "tag" if kind == "tags" else "branch",
                         (ref.get("commit_id") or "")[:12], layout))
    if not rows:
        print(f"No datasets in '{repo}' yet. Upload one with: kubecore-dataset sync <dir> --branch <name>")
        return 0
    print(f"Datasets in '{repo}' (use the name as data-ref):")
    width = max(len(r[0]) for r in rows)
    for name, kind, commit, layout in rows:
        print(f"  {name:<{width}}  {kind:<6}  {commit}  {layout}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kubecore-dataset",
        description="Log in, validate, and incrementally sync YOLO-pose datasets "
                    "to lakeFS for the ML pipeline.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("--url", help="lakeFS ingress URL (or env LAKEFS_URL)")
        sp.add_argument("--repo", help="lakeFS repository (or env LAKEFS_REPO)")
        sp.add_argument("--branch", help="dataset name = the data-ref you pick when running "
                                         "(or env LAKEFS_BRANCH, default main)")
        sp.add_argument("--from", dest="source", default=None,
                        help="when --branch is new, start it as a copy of this branch/tag "
                             "(default: the repository's default branch); only changed files upload")
        sp.add_argument("--data-version", default=None,
                        help=argparse.SUPPRESS)  # removed; parsed only to explain why
        sp.add_argument("--yes", action="store_true",
                        help="don't ask before deleting remote files that are not in your folder")
        sp.add_argument("--remove-legacy", action="store_true",
                        help="also delete old-layout dataset/<version>/ folders on the branch")
        sp.add_argument("--concurrency", type=int, default=16)
        sp.add_argument("--paste", action="store_true",
                        help="skip the browser login; use guided cookie paste")
        sp.add_argument("--prefix", default="",
                        help="advanced: override the standard dataset/ location")
        sp.add_argument("--allow-prefix", action="store_true",
                        help=argparse.SUPPRESS)  # kept so old commands still parse; no longer needed
        sp.add_argument("--skip-validation", action="store_true")
        sp.add_argument("--dry-run", action="store_true")

    lp = sub.add_parser("login", help="log in to lakeFS via the browser")
    lp.add_argument("--url", help="lakeFS ingress URL (or env LAKEFS_URL)")
    lp.add_argument("--force", action="store_true", help="ignore any cached session")
    lp.add_argument("--paste", action="store_true", help="use guided cookie paste")
    lp.set_defaults(func=cmd_login)

    vp = sub.add_parser("validate", help="validate a local dataset directory")
    vp.add_argument("dataset_dir", help="path to the local dataset directory")
    vp.set_defaults(func=cmd_validate)

    spc = sub.add_parser("sync", help="incrementally sync a dataset to lakeFS")
    spc.add_argument("dataset_dir", help="path to the local dataset directory")
    add_common(spc)
    spc.set_defaults(func=cmd_sync)

    up = sub.add_parser("upload", help="login + validate + sync (the one-liner)")
    up.add_argument("dataset_dir", help="path to the local dataset directory")
    add_common(up)
    up.set_defaults(func=cmd_sync)

    ls = sub.add_parser("list", help="list the datasets (branches and tags) in the repository")
    ls.add_argument("--url", help="lakeFS ingress URL (or env LAKEFS_URL)")
    ls.add_argument("--repo", help="lakeFS repository (or env LAKEFS_REPO)")
    ls.add_argument("--paste", action="store_true", help="use guided cookie paste")
    ls.set_defaults(func=cmd_list)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except requests.exceptions.ConnectionError as exc:
        sys.exit(unreachable_message(exc))


def unreachable_message(exc: Exception) -> str:
    """One readable line instead of a urllib3 traceback."""
    host = getattr(getattr(exc, "request", None), "url", "") or ""
    host = host.split("/")[2] if host.count("/") >= 2 else "lakeFS"
    return (f"ERROR: cannot reach {host}. Check the lakeFS link in "
            ".kubecore/dataset-config.yaml (or --url) and your network, then try again.")


if __name__ == "__main__":
    sys.exit(main())
