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

Callers upload under ``dataset_prefix(version)``, i.e. the platform-standard
``s3://<repo>/<data-ref>/dataset/<data-version>/`` that config-validation and
dataset-loading read. Because the sync mirrors, callers that act for a person
pass ``confirm_deletes=True`` so remote files are never deleted silently.
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


def dataset_prefix(version: str) -> str:
    """Where a dataset lives inside its lakeFS branch: ``dataset/<version>``.

    PLATFORM STANDARD: the pipeline (config-validation and dataset-loading)
    reads ``s3://<repo>/<data-ref>/dataset/<data-version>/`` and nothing else,
    with data-version defaulting to data-ref. Every upload path must derive its
    location from here; a flat ``dataset/`` or the branch root uploads fine and
    then fails the run with "dataset path not found or empty".
    """
    return f"dataset/{version.strip('/')}"


def _confirm_deletes(plan: "SyncPlan", repo: str, branch: str) -> None:
    """Sync MIRRORS the local folder, so files on the target that are not in it
    get deleted. Say so and ask, instead of doing it silently."""
    n = len(plan.delete)
    print(f"\n⚠️  '{branch}' in '{repo}' has {n} file(s) that are NOT in your local "
          "folder.\n    Uploading makes the dataset match your folder, so they will be "
          "DELETED:")
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
    for obj in client.list_objects(repo, ref, prefix):
        out[obj["path"]] = obj.get("checksum", "")
    return out


def plan_sync(root: pathlib.Path, client: LakeFSClient, repo: str, branch: str,
              prefix: str) -> SyncPlan:
    local = _local_index(root, prefix)
    remote = _remote_index(client, repo, branch, prefix)
    plan = SyncPlan()

    for repo_path, (local_path, md5) in local.items():
        remote_sum = remote.get(repo_path)
        if remote_sum is None or remote_sum != md5:
            plan.add.append((local_path, repo_path))
        else:
            plan.unchanged += 1

    for repo_path in remote:
        if repo_path not in local:
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
         confirm_deletes: bool = False) -> str | None:
    """Execute the incremental sync and commit. Returns the commit id (or None)."""
    print(f"Diffing local tree against lakefs://{repo}/{branch}"
          f"{('/' + prefix) if prefix else ' (root)'} …")
    plan = plan_sync(root, client, repo, branch, prefix)

    print(f"  add/changed: {len(plan.add)}")
    print(f"  delete:      {len(plan.delete)}")
    print(f"  unchanged:   {plan.unchanged}")

    if plan.changes == 0:
        print("Nothing to sync — branch already matches local.")
        return client.branch_tip(repo, branch)

    if dry_run:
        for _, rp in plan.add[:20]:
            print(f"    + {rp}")
        for rp in plan.delete[:20]:
            print(f"    - {rp}")
        print("(dry run — no changes made)")
        return None

    if confirm_deletes and plan.delete:
        _confirm_deletes(plan, repo, branch)

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
        "validated": "true",
        "tool": "kubecore-dataset-cli",
    }
    metadata.update(extra_metadata or {})
    print("\nCommitting on branch …")
    commit_id = client.commit(repo, branch, msg, metadata)
    print(f"✓ Committed. id={commit_id}")
    return commit_id
