"""Datasets: one lakeFS repository ``dataset-<name>`` each, versions are tags v1, v2, ... on ``main``.

Data model (PRD kaos#1283): ``latest`` is the head of ``main``; a run picks
``<dataset-repo>@<version>``; changes reach ``main`` only through a pull request
(except the initial scaffold that ``create_dataset`` commits, as kaos-lake does).
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import re
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from .errors import DatasetError, LakeFSError, NotFoundError
from .lakefs import LakeFS
from .transfer import apply_plan, plan_mirror, upload_tree

DATASET_PREFIX = "dataset-"
MAIN = "main"
LATEST = "latest"
LABEL_KIND, LABEL_TEMPLATE, LABEL_DESCRIPTION = "kaos.kind", "kaos.template", "kaos.description"
LABEL_DEFAULT, LABEL_LOCATION, LABEL_SHARED = "kaos.default", "kaos.location", "kaos.shared_with"
STORAGE_BASE_ENV = "KUBECORE_STORAGE_NAMESPACE_BASE"

_NAME_RE = re.compile(r"^[a-z0-9-]{3,48}$")
_VERSION_RE = re.compile(r"^v[1-9][0-9]*$")


def dataset_repo(name: str) -> str:
    """``dataset-<name>`` from ``name`` or ``dataset-<name>``; validates the 3-48 char ``[a-z0-9-]`` rule."""
    short = name[len(DATASET_PREFIX):] if name.startswith(DATASET_PREFIX) else name
    if not _NAME_RE.match(short):
        raise DatasetError(
            f"invalid dataset name {short!r}: use 3 to 48 characters from a-z, 0-9 and '-' "
            f"(the repository is called {DATASET_PREFIX}<name>).")
    return DATASET_PREFIX + short


@dataclass(frozen=True)
class DatasetRef:
    """A pinned choice ``<dataset-repo>@<version>``; version is ``latest`` or ``vN``."""
    repo: str
    version: str

    @classmethod
    def parse(cls, text: str) -> "DatasetRef":
        """Parse ``dataset-x@v2``; raises DatasetError saying what is wrong and what is valid."""
        text = (text or "").strip()
        repo, sep, version = text.partition("@")
        if not sep or not repo or not version:
            raise DatasetError(f"{text!r} is not a dataset reference: write <dataset-repo>@<version>, "
                               f"e.g. dataset-default@v2 or dataset-default@{LATEST}.")
        if "@" in version:
            raise DatasetError(f"{text!r} has more than one '@': write <dataset-repo>@<version>.")
        if not repo.startswith(DATASET_PREFIX) or not _NAME_RE.match(repo[len(DATASET_PREFIX):]):
            raise DatasetError(f"{repo!r} is not a dataset repository: names look like "
                               f"{DATASET_PREFIX}<name> (3 to 48 characters from a-z, 0-9, '-').")
        if version != LATEST and not _VERSION_RE.match(version):
            raise DatasetError(f"{version!r} is not a version: use {LATEST} or v1, v2, ...")
        return cls(repo, version)

    def __str__(self) -> str:
        return f"{self.repo}@{self.version}"


@dataclass
class DatasetInfo:
    """One row of ``list_datasets``: the repository and its labels."""
    repo: str
    description: str = ""
    template: str = ""
    default: bool = False
    location: str = ""
    labels: dict = field(default_factory=dict)


def _client(client: Optional[LakeFS]) -> LakeFS:
    return client or LakeFS.connect()


def resolve(ref: DatasetRef, client: Optional[LakeFS] = None) -> str:
    """The commit id ``ref`` points at (tag commit for ``vN``, head of main for ``latest``)."""
    c = _client(client)
    try:
        if ref.version == LATEST:
            return c.branch_commit(ref.repo, MAIN)
        return c.tag_commit(ref.repo, ref.version)
    except NotFoundError as exc:
        have = ", ".join(versions(ref.repo, c)) if c.repository(ref.repo) else None
        if have is None:
            raise DatasetError(f"dataset {ref.repo} does not exist. List datasets with `kubecore dataset list`.") from exc
        raise DatasetError(f"{ref.repo} has no version {ref.version}. "
                           f"Available: {have or 'none yet (release one with `kubecore dataset release`)'}.") from exc


def list_datasets(client: Optional[LakeFS] = None) -> list:
    """Every ``dataset-*`` repository the caller can see, with its labels."""
    c = _client(client)
    rows = []
    for repo in sorted(r["id"] for r in c.repositories() if r["id"].startswith(DATASET_PREFIX)):
        try:
            labels = c.metadata(repo)
        except LakeFSError:
            labels = {}  # unlabelled or unreadable metadata must not hide the dataset
        rows.append(DatasetInfo(
            repo=repo, labels=labels, description=labels.get(LABEL_DESCRIPTION, ""),
            template=labels.get(LABEL_TEMPLATE, ""), location=labels.get(LABEL_LOCATION, ""),
            default=str(labels.get(LABEL_DEFAULT, "")).lower() == "true"))
    return rows


def _version_number(tag: str) -> Optional[int]:
    return int(tag[1:]) if _VERSION_RE.match(tag) else None


def versions(repo: str, client: Optional[LakeFS] = None) -> list:
    """Version tags of ``repo`` as ``["v1", "v2", ...]`` in numeric order."""
    c = _client(client)
    nums = sorted(n for n in (_version_number(t["id"]) for t in c.tags(repo)) if n)
    return [f"v{n}" for n in nums]


def release(repo: str, client: Optional[LakeFS] = None) -> str:
    """Tag the head of ``main`` with the next ``vN`` and return it (v10 follows v9)."""
    c = _client(client)
    head = c.branch_commit(repo, MAIN)
    tags = {t["id"]: t["commit_id"] for t in c.tags(repo)}
    nums = [n for n in (_version_number(t) for t in tags) if n]
    for tag, commit in tags.items():
        if commit == head and _version_number(tag):
            raise DatasetError(f"nothing new to release: the head of {repo} main is already {tag}. "
                               "Merge a pull request first.")
    version = f"v{max(nums, default=0) + 1}"
    c.create_tag(repo, version, head)
    return version


def _storage_namespace(c: LakeFS, repo: str) -> str:
    """Storage for a new repository: a sibling of an existing one (or the env base)."""
    base = os.environ.get(STORAGE_BASE_ENV)
    if not base:
        existing = [r["storage_namespace"] for r in c.repositories() if r.get("storage_namespace")]
        if not existing:
            raise DatasetError(f"cannot choose storage for {repo}: no repository exists to copy it from. "
                               f"Set {STORAGE_BASE_ENV} (e.g. gs://bucket/project).")
        base = existing[0].rstrip("/").rsplit("/", 1)[0]
    return f"{base.rstrip('/')}/{repo}"


def ensure_repository(c: LakeFS, repo: str, labels: dict) -> bool:
    """Create ``repo`` with ``labels`` unless it exists; returns True when it was created."""
    if c.repository(repo):
        return False
    c.create_repository(repo, _storage_namespace(c, repo), MAIN)
    c.set_metadata(repo, labels)
    return True


def create_dataset(name: str, fmt_name: str = "ultralytics", description: str = "",
                   client: Optional[LakeFS] = None, **skeleton_args) -> str:
    """Create ``dataset-<name>`` labelled for ``fmt_name`` and commit the format's skeleton to main.

    Returns the repository name. Fails if the repository already exists.
    """
    from .formats import get_format
    c, fmt = _client(client), get_format(fmt_name)
    repo = dataset_repo(name)
    files = fmt.creator.skeleton(description=description, **skeleton_args)
    labels = {LABEL_KIND: "dataset", LABEL_TEMPLATE: fmt.name}
    if description:
        labels[LABEL_DESCRIPTION] = description
    if not ensure_repository(c, repo, labels):
        raise DatasetError(f"{repo} already exists. Push to it with `kubecore dataset push <dir> {repo}`.")
    with tempfile.TemporaryDirectory() as tmp:
        for rel, content in files.items():
            target = pathlib.Path(tmp, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        upload_tree(c, repo, MAIN, pathlib.Path(tmp))
    c.commit(repo, MAIN, f"Create {fmt.name} dataset skeleton", {"kaos.template": fmt.name})
    return repo


@dataclass
class PublishResult:
    """Outcome of ``publish_tree``."""
    repo: str
    created: bool
    commit: str
    branch: str
    pull_id: Optional[str] = None
    pull_url: Optional[str] = None


def publish_tree(local_dir, repo: str, message: str, via_pull_request: bool = True,
                 labels: Optional[dict] = None, client: Optional[LakeFS] = None) -> PublishResult:
    """Mirror ``local_dir`` into ``repo``: draft branch, commit, pull request into main.

    Creates the repository (with ``labels``) when missing. With
    ``via_pull_request=False`` the commit goes straight to main (admin use only).
    Raises DatasetError when the directory is identical to main.
    """
    c, root = _client(client), pathlib.Path(local_dir)
    created = ensure_repository(c, repo, labels or {LABEL_KIND: "dataset"})
    plan = plan_mirror(c, repo, MAIN, root)
    if plan.empty:
        raise DatasetError(f"nothing to publish: {root} is identical to {repo} main.")
    branch = MAIN
    if via_pull_request:
        branch = "draft/" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        c.create_branch(repo, branch, MAIN)
    apply_plan(c, repo, branch, plan)
    commit = c.commit(repo, branch, message)
    if not via_pull_request:
        return PublishResult(repo, created, commit, branch)
    pull_id = c.create_pull(repo, branch, MAIN, message)
    return PublishResult(repo, created, commit, branch, pull_id,
                         f"{c.base_url}/repositories/{repo}/pulls/{pull_id}")


def materialize(ref: DatasetRef, dest=None, fmt_name: Optional[str] = None,
                client: Optional[LakeFS] = None) -> pathlib.Path:
    """Local, trainable copy of ``ref`` in its format's layout; returns the format's entry file.

    ``fmt_name`` defaults to the repository's ``kaos.template`` label, then ``ultralytics``.
    """
    from .formats import get_format
    c = _client(client)
    if fmt_name is None:
        try:
            fmt_name = c.metadata(ref.repo).get(LABEL_TEMPLATE)
        except LakeFSError:
            fmt_name = None
    return get_format(fmt_name or "ultralytics").consumer.materialize(ref, dest, c)
