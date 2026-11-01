"""Run outputs: each ML app writes its results to its own ``outputs-<app>`` repository.

One commit on ``main`` per run, under ``<kind>/<experiment>/<run>/`` (kind is
``checkpoints`` by default). Pipelines never write to a ``dataset-*`` repository.
The repository is declared and created by the platform, never here.
"""
from __future__ import annotations

import pathlib
import re
from typing import Optional

from .errors import DatasetError, NotFoundError
from .lakefs import LakeFS
from .transfer import upload_tree

OUTPUTS_PREFIX = "outputs-"
MAIN = "main"
_APP_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=-]*$")


def outputs_repo(app: str) -> str:
    """``outputs-<app>`` for an app name (a name already prefixed is returned as is)."""
    short = app[len(OUTPUTS_PREFIX):] if app.startswith(OUTPUTS_PREFIX) else app
    if not _APP_RE.match(short):
        raise DatasetError(f"invalid app name {app!r}: use lowercase letters, digits and '-'.")
    return OUTPUTS_PREFIX + short


def _segment(label: str, value: str) -> str:
    if not _SEGMENT_RE.match(value or "") or ".." in value:
        raise DatasetError(f"invalid {label} {value!r}: use letters, digits, '.', '_', '-' and '=' (no '/').")
    return value


def run_prefix(experiment: str, run: str, kind: str = "checkpoints") -> str:
    """Repository path under which a run's results of ``kind`` live: ``<kind>/<experiment>/<run>/``."""
    return f"{_segment('kind', kind)}/{_segment('experiment', experiment)}/{_segment('run', run)}/"


def run_branch(run: str) -> str:
    """Branch a run writes on before merging into main: ``run-<run>`` with unsafe characters replaced."""
    return "run-" + re.sub(r"[^A-Za-z0-9_-]", "-", run)


def write_run(app: str, experiment: str, run: str, local_dir, kind: str = "checkpoints",
              client: Optional[LakeFS] = None) -> str:
    """Write ``local_dir`` to ``outputs-<app>`` under the run's prefix; returns the merge commit on main.

    Concurrency-safe: the run uploads and commits on its own branch ``run-<run>`` (created from main;
    a leftover branch from a re-run of the same id is replaced), which is merged into main and deleted,
    so simultaneous runs never share main's staging area. Main gets exactly one new commit per run.
    """
    c, root = client or LakeFS.connect(), pathlib.Path(local_dir)
    repo, prefix, branch = outputs_repo(app), run_prefix(experiment, run, kind), run_branch(run)
    if not root.is_dir():
        raise DatasetError(f"{root} is not a directory.")
    try:
        c.branch_commit(repo, MAIN)
    except NotFoundError as exc:
        raise DatasetError(f"{repo} does not exist: the platform creates it for each ML app. "
                           "Check the app name.") from exc
    c.delete_branch(repo, branch)  # replace a stale branch of a previous attempt of this run
    c.create_branch(repo, branch, MAIN)
    try:
        if upload_tree(c, repo, branch, root, prefix) == 0:
            raise DatasetError(f"{root} has no files to write.")
        meta = {"app": app, "experiment": experiment, "run": run, "kind": kind}
        message = f"{kind}: {experiment}/{run}"
        c.commit(repo, branch, message, meta)
        return c.merge(repo, branch, MAIN, message, meta)
    finally:
        c.delete_branch(repo, branch)
