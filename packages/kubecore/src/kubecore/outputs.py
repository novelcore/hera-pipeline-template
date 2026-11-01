"""Run outputs: each ML app writes its results to its own ``outputs-<app>`` repository.

One commit on ``main`` per step per run (a merge from the run's own branch), under
``<kind>/<experiment>/<run>/`` (kind is ``checkpoints`` by default). Pipelines never write to a ``dataset-*`` repository.
The repository is declared and created by the platform, never here.
"""
from __future__ import annotations

import pathlib
import re
import tempfile
from typing import Optional

from .errors import DatasetError, LakeFSError, NotFoundError
from .lakefs import LakeFS
from .transfer import upload_files, upload_tree

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


def run_branch(run: str, kind: str = "checkpoints") -> str:
    """Branch one step of a run writes on: ``run-<run>-<kind>`` with unsafe characters replaced."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", f"run-{run}-{kind}")


def _files_of(source) -> dict:
    """``{name: Path}`` for a list of files (placed by base name)."""
    out = {}
    for item in source:
        path = pathlib.Path(item)
        if not path.is_file():
            raise DatasetError(f"{path} is not a file.")
        if path.name in out:
            raise DatasetError(f"two files are both called {path.name!r}; save a folder instead.")
        out[path.name] = path
    return out


class RunWriter:
    """Durable, idempotent writer of one step's outputs (one kind) of one run.

    Everything is saved and committed on the run's own branch ``run-<run>-<kind>`` (created from main,
    or REUSED when it exists, so a retry or a preempted pod resumes). ``finish`` merges the branch into
    main (exactly one new commit on main per step per run) and deletes it. An exception inside the
    ``with`` block neither merges nor deletes. Needs write rights on ``outputs-<app>`` only.
    """

    def __init__(self, app: str, experiment: str, run: str, kind: str = "checkpoints",
                 client: Optional[LakeFS] = None):
        self.app, self.experiment, self.run, self.kind = app, experiment, run, kind
        self.repo, self.prefix = outputs_repo(app), run_prefix(experiment, run, kind)
        self.branch = run_branch(run, kind)
        self.client = client or LakeFS.connect()
        self._finished: Optional[str] = None

    @property
    def metadata(self) -> dict:
        return {"app": self.app, "experiment": self.experiment, "run": self.run, "kind": self.kind}

    def open(self) -> "RunWriter":
        """Make sure the run branch exists (never deletes an existing one)."""
        c = self.client
        try:
            c.branch_commit(self.repo, MAIN)
        except NotFoundError as exc:
            raise DatasetError(f"{self.repo} does not exist: the platform creates it for each ML app. "
                               "Check the app name.") from exc
        if not c.branch_exists(self.repo, self.branch):
            try:
                c.create_branch(self.repo, self.branch, MAIN)
            except LakeFSError as exc:
                if exc.status != 409:  # 409: a parallel attempt created it first, which is fine
                    raise
        return self

    def __enter__(self) -> "RunWriter":
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None and self._finished is None:
            self.finish()
        return False  # on an exception: no merge, no delete; the retry resumes from the branch

    def save(self, source, message: Optional[str] = None) -> str:
        """Upload a folder, a file or a list of files under the run's prefix and commit ON THE RUN BRANCH.

        Durable as soon as it returns. Saving identical content again is a success and returns the
        existing commit. Returns the commit id.
        """
        if isinstance(source, (str, pathlib.Path)) and pathlib.Path(source).is_dir():
            count = upload_tree(self.client, self.repo, self.branch, pathlib.Path(source), self.prefix)
        else:
            items = [source] if isinstance(source, (str, pathlib.Path)) else list(source)
            files = {self.prefix + name: p for name, p in _files_of(items).items()}
            count = upload_files(self.client, self.repo, self.branch, files)
        if count == 0:
            raise DatasetError(f"{source} has no files to save.")
        return self.client.commit(self.repo, self.branch, message or f"{self.kind}: {self.experiment}/{self.run}",
                                  self.metadata, tolerate_empty=True)

    def latest(self, path_prefix: str = "", dest=None) -> Optional[pathlib.Path]:
        """Download what the run branch already holds so training can resume; None when there is nothing.

        ``path_prefix`` is relative to the run's prefix. If it is empty or ends with ``/`` the whole
        folder is downloaded and its local path returned; otherwise the most recently written object
        whose path starts with it is downloaded and its local file path returned.
        """
        c, base = self.client, self.prefix + path_prefix
        objs = list(c.list_objects(self.repo, self.branch, base))
        if not objs:
            return None
        root = pathlib.Path(dest) if dest else pathlib.Path(tempfile.gettempdir()) / "kubecore-runs" / self.repo / self.branch
        if path_prefix == "" or path_prefix.endswith("/"):
            for o in objs:
                c.download_object(self.repo, self.branch, o["path"], root / o["path"][len(self.prefix):])
            return root / path_prefix
        newest = max(objs, key=lambda o: (o.get("mtime", 0), o["path"]))
        target = root / newest["path"][len(self.prefix):]
        c.download_object(self.repo, self.branch, newest["path"], target)
        return target

    def finish(self, metadata: Optional[dict] = None) -> str:
        """Merge the run branch into main (one commit) and delete the branch; returns the main commit.

        The merge commit carries ``{app, experiment, run, kind, **metadata}`` (dataset ref/commit,
        MLflow run id, ...). Nothing to merge counts as success and returns main's head. Idempotent.
        """
        if self._finished is not None:
            return self._finished
        c = self.client
        commit = c.merge(self.repo, self.branch, MAIN, f"{self.kind}: {self.experiment}/{self.run}",
                         {**self.metadata, **(metadata or {})}, tolerate_empty=True)
        c.delete_branch(self.repo, self.branch)
        self._finished = commit
        return commit


def run(app: str, experiment: str, run: str, kind: str = "checkpoints",
        client: Optional[LakeFS] = None) -> RunWriter:
    """``with outputs.run(app, experiment, run, kind) as r:`` ... see ``RunWriter``."""
    return RunWriter(app, experiment, run, kind, client)


def write_run(app: str, experiment: str, run: str, local_dir, kind: str = "checkpoints",
              client: Optional[LakeFS] = None, metadata: Optional[dict] = None) -> str:
    """Open the run writer, save ``local_dir`` once, finish; returns the merge commit on main."""
    if not pathlib.Path(local_dir).is_dir():
        raise DatasetError(f"{local_dir} is not a directory.")
    with RunWriter(app, experiment, run, kind, client) as r:
        r.save(local_dir)
        return r.finish(metadata)
