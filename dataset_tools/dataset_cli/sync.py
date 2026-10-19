"""Incremental sync of a local dataset directory to a lakeFS branch.

Unlike a blind re-upload, this diffs local vs remote by CONTENT CHECKSUM and
applies THREE actions so the branch mirrors the local tree exactly:

    add/changed : local-only or checksum-differs  -> POST object
    delete      : remote-only                     -> DELETE object   (the fix)
    unchanged   : same checksum                   -> skip

lakeFS stores an MD5-of-content checksum per object (returned by objects/ls),
which we compare to a local MD5 — cheap and exact, catching same-name content
edits that a name+size diff would miss. After a clean pass it makes ONE commit
on the branch.

Callers upload under ``dataset_prefix()``, i.e. the platform-standard
``s3://<repo>/<data-ref>/dataset/`` that config-validation and dataset-loading
read. Because the sync mirrors, callers that act for a person pass
``confirm_deletes=True`` so remote files are never deleted silently.

A dataset uploaded before the version folder was dropped sits one level deeper,
at ``dataset/<data-version>/`` (its own ``data.yaml``). Apps still on the old
step code read it there, and one lakeFS repo serves every app of a project, so
the mirror never deletes such a folder unless asked (``remove_legacy``).
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import pathlib
import sys
import threading
import time
from dataclasses import dataclass, field

from .lakefs_client import LakeFSClient, LakeFSError


# Branches the platform owns; a dataset must never be uploaded onto them.
# `outputs` holds pipeline outputs (checkpoints, quantization artifacts).
RESERVED_BRANCHES = frozenset({"outputs"})


def dataset_prefix() -> str:
    """Where a dataset lives inside its lakeFS branch: ``dataset``.

    PLATFORM STANDARD: the pipeline (config-validation and dataset-loading)
    reads ``s3://<repo>/<data-ref>/dataset/``, so the same file has the same
    path on every branch and lakeFS can branch, diff and merge datasets. Every
    upload path must derive its location from here.
    """
    return "dataset"


def check_branch_name(branch: str) -> None:
    """Refuse a branch the platform owns."""
    if branch in RESERVED_BRANCHES:
        sys.exit(f"ERROR: '{branch}' is reserved for pipeline outputs; pick another dataset name.")


def open_branch(client: LakeFSClient, repo: str, branch: str, source: str | None,
                dry_run: bool = False) -> str | None:
    """Make sure ``branch`` exists. Returns the ref it was created from, or None
    when it already existed. A new branch starts as a copy of ``source`` (the
    repository's default branch when None), so the sync uploads only the files
    that differ from it. A dry run creates nothing."""
    if client.branch_exists(repo, branch):
        if source:
            print(f"Branch '{branch}' already exists — --from {source} is ignored.")
        return None
    source = source or client.default_branch(repo)
    if dry_run:
        print(f"Branch '{branch}' does not exist — a real run creates it from '{source}'.")
        return source
    print(f"Branch '{branch}' does not exist — creating it from '{source}'.")
    client.ensure_branch(repo, branch, source)
    return source


def _confirm_deletes(plan: "SyncPlan", repo: str, branch: str,
                     created_from: str | None = None) -> None:
    """Sync MIRRORS the local folder, so files on the target that are not in it
    get deleted. Say so and ask, instead of doing it silently."""
    n = len(plan.delete)
    print(f"\n⚠️  '{branch}' in '{repo}' has {n} file(s) that are NOT in your local "
          "folder.\n    Uploading makes the dataset match your folder, so they will be "
          "DELETED:")
    if created_from:
        print(f"    ('{branch}' was just created as a copy of '{created_from}', so these are "
              f"'{created_from}''s files; '{created_from}' itself is not touched.)")
    for rp in plan.delete[:10]:
        print(f"      - {rp}")
    if n > 10:
        print(f"      … and {n - 10} more")
    print("    To keep them, upload under a different dataset name instead.")
    if not sys.stdin.isatty():
        sys.exit("Aborted: this would delete files and there is no terminal to "
                 "confirm on. Re-run with --yes if the deletions are intended.")
    sys.stdout.write(f"Delete these {n} file(s)? [y/N] ")
    sys.stdout.flush()
    try:
        answer = sys.stdin.readline().strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer not in ("y", "yes"):
        sys.exit("Aborted — nothing was uploaded or deleted.")


@dataclass
class SyncPlan:
    add: list[tuple[pathlib.Path, str]] = field(default_factory=list)   # (local, repo_path)
    delete: list[str] = field(default_factory=list)                     # repo_path
    unchanged: int = 0
    legacy: list[str] = field(default_factory=list)   # old-layout dataset folders kept

    @property
    def changes(self) -> int:
        return len(self.add) + len(self.delete)


def _md5(path: pathlib.Path, _bufsize: int = 1 << 20) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def _local_index(root: pathlib.Path, prefix: str) -> dict[str, tuple[pathlib.Path, str]]:
    """Map repo_path -> (local_path, md5) for every file under root."""
    index: dict[str, tuple[pathlib.Path, str]] = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            repo_path = f"{prefix}/{rel}" if prefix else rel
            index[repo_path] = (p, _md5(p))
    return index


def _remote_index(client: LakeFSClient, repo: str, ref: str, prefix: str) -> dict[str, str]:
    """Map repo_path -> checksum for every object on the ref under prefix."""
    out: dict[str, str] = {}
    # The trailing slash keeps a sibling that merely starts with the same name
    # (dataset2/ next to dataset/) out of the index, and so out of the deletes.
    for obj in client.list_objects(repo, ref, f"{prefix}/" if prefix else ""):
        out[obj["path"]] = obj.get("checksum", "")
    return out


def _legacy_roots(remote: dict[str, str], local: dict, prefix: str) -> list[str]:
    """Old-layout datasets under ``prefix``: a ``<prefix>/<sub>/data.yaml`` on the
    remote that the local folder does not have (so it is not part of this dataset)."""
    roots = set()
    head = f"{prefix}/" if prefix else ""
    for repo_path in remote:
        rest = repo_path[len(head):]
        sub, _, name = rest.partition("/")
        if name == "data.yaml" and repo_path not in local:
            roots.add(f"{head}{sub}/")
    return sorted(roots)


def plan_sync(root: pathlib.Path, client: LakeFSClient, repo: str, branch: str,
              prefix: str, remove_legacy: bool = False) -> SyncPlan:
    local = _local_index(root, prefix)
    remote = _remote_index(client, repo, branch, prefix)
    plan = SyncPlan()
    if not remove_legacy:
        plan.legacy = _legacy_roots(remote, local, prefix)

    for repo_path, (local_path, md5) in local.items():
        remote_sum = remote.get(repo_path)
        if remote_sum is None or remote_sum != md5:
            plan.add.append((local_path, repo_path))
        else:
            plan.unchanged += 1

    for repo_path in remote:
        if repo_path not in local and not any(repo_path.startswith(r) for r in plan.legacy):
            plan.delete.append(repo_path)

    return plan


def _run_pool(items, fn, label: str, concurrency: int) -> list[str]:
    """Run fn over items with a thread pool; return failure strings."""
    total = len(items)
    if total == 0:
        return []
    lock = threading.Lock()
    done = 0
    failures: list[str] = []
    start = time.time()

    def worker(item):
        nonlocal done
        try:
            fn(item)
            err = None
        except LakeFSError as exc:
            err = str(exc)
        with lock:
            done += 1
            if err:
                failures.append(err)
            if done % 200 == 0 or done == total:
                elapsed = time.time() - start
                rate = done / elapsed if elapsed else 0
                eta = (total - done) / rate if rate else 0
                print(f"  {label}: {done}/{total} "
                      f"({rate:.0f}/s, ETA {eta/60:.1f}m, failures {len(failures)})")

    with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
        list(ex.map(worker, items))
    return failures


def sync(root: pathlib.Path, client: LakeFSClient, repo: str, branch: str,
         prefix: str = "", concurrency: int = 16, dry_run: bool = False,
         commit_message: str | None = None, extra_metadata: dict | None = None,
         confirm_deletes: bool = False, remove_legacy: bool = False,
         created_from: str | None = None, validated: bool = True) -> str | None:
    """Execute the incremental sync and commit. Returns the commit id (or None)."""
    # A dry run against a branch that does not exist yet diffs the ref it would
    # be created from.
    diff_ref = created_from if (dry_run and created_from) else branch
    print(f"Diffing local tree against lakefs://{repo}/{diff_ref}"
          f"{('/' + prefix) if prefix else ' (root)'} …")
    plan = plan_sync(root, client, repo, diff_ref, prefix, remove_legacy=remove_legacy)

    print(f"  add/changed: {len(plan.add)}")
    print(f"  delete:      {len(plan.delete)}")
    print(f"  unchanged:   {plan.unchanged}")
    for r in plan.legacy:
        print(f"  kept:        {r} (dataset in the old layout — apps on older step code "
              "may still read it; --remove-legacy deletes it)")

    if plan.changes == 0:
        print("Nothing to sync — branch already matches local.")
        return None if dry_run else client.branch_tip(repo, branch)

    if dry_run:
        for _, rp in plan.add[:20]:
            print(f"    + {rp}")
        for rp in plan.delete[:20]:
            print(f"    - {rp}")
        print("(dry run — no changes made)")
        return None

    if confirm_deletes and plan.delete:
        _confirm_deletes(plan, repo, branch, created_from)

    # 1) uploads
    up_failures = _run_pool(
        plan.add,
        lambda item: client.upload_object(repo, branch, item[1], item[0]),
        "upload", concurrency,
    )
    # 2) deletions (the missing piece vs the old additive-only tools)
    del_failures = _run_pool(
        plan.delete,
        lambda rp: client.delete_object(repo, branch, rp),
        "delete", concurrency,
    )

    failures = up_failures + del_failures
    if failures:
        print(f"\n✗ {len(failures)} operation(s) failed — NOT committing. First 10:")
        for f in failures[:10]:
            print(f"    {f}")
        sys.exit(1)

    # 3) single commit on the branch
    msg = commit_message or (
        f"dataset sync: +{len(plan.add)} -{len(plan.delete)} "
        f"={plan.unchanged} unchanged"
    )
    metadata = {
        "added": len(plan.add),
        "deleted": len(plan.delete),
        "unchanged": plan.unchanged,
        "validated": "true" if validated else "false",
        "tool": "kubecore-dataset-cli",
    }
    metadata.update(extra_metadata or {})
    print("\nCommitting on branch …")
    commit_id = client.commit(repo, branch, msg, metadata)
    print(f"✓ Committed. id={commit_id}")
    return commit_id
