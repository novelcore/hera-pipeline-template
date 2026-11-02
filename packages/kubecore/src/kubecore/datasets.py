"""Datasets: one lakeFS repository ``dataset-<name>`` each, versions are tags v1, v2, ... on ``main``.

Data model (PRD kaos#1283): ``latest`` is the head of ``main``; a run picks
``<dataset-repo>@<version>``; changes reach ``main`` only through a pull request
(except the initial scaffold that ``create_dataset`` commits, as kaos-lake does).
``<owner-project>/dataset-<name>@<version>`` reads a dataset another project of the
organisation shares with this one (F-12): read-only, from the owner's lakeFS.
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import re
import tempfile
from dataclasses import dataclass, field, replace
from typing import Optional

from .errors import DatasetError, LakeFSError, NotFoundError
from .lakefs import LakeFS
from .transfer import apply_plan, plan_mirror, upload_tree

DATASET_PREFIX = "dataset-"
MAIN = "main"
LATEST = "latest"
LABEL_KIND, LABEL_TEMPLATE, LABEL_DESCRIPTION = "kaos.kind", "kaos.template", "kaos.description"
LABEL_DEFAULT, LABEL_LOCATION, LABEL_SHARED = "kaos.default", "kaos.location", "kaos.shared_with"
NO_TEMPLATE = "none"   # create_dataset(fmt_name="none"): an empty repository
STORAGE_BASE_ENV = "KUBECORE_STORAGE_NAMESPACE_BASE"

_NAME_RE = re.compile(r"^[a-z0-9-]{3,48}$")
_VERSION_RE = re.compile(r"^v[1-9][0-9]*$")
_REPO_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")   # any valid lakeFS repository name
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")  # vN, latest, branch, tag or commit id
_COMMIT_RE = re.compile(r"^[A-Za-z0-9_-]{6,128}$")
_OWNER_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")   # a project name, as kaos-lake validates it


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
    """A choice ``[<owner>/]<repository>@<ref>``.

    Without an owner: ANY lakeFS repository of the own project (not only ``dataset-*``). With an
    owner: a ``dataset-*`` repository another project of the organisation shares with this one,
    read from that project's lakeFS (``owner`` is None for the own project).

    ``version`` is ``vN`` (a tag), ``latest`` (head of the default branch), a branch, a tag or a
    commit id. ``commit`` optionally pins the exact commit (e.g. the one ``dataset-loading`` resolved);
    when set, ``resolve`` returns it without asking lakeFS.
    """
    repo: str
    version: str
    commit: Optional[str] = None
    owner: Optional[str] = None

    def with_commit(self, commit: str) -> "DatasetRef":
        """A copy of this ref pinned to ``commit``."""
        if not _COMMIT_RE.match(commit or ""):
            raise DatasetError(f"{commit!r} is not a commit id.")
        return replace(self, commit=commit)

    @classmethod
    def parse(cls, text: str, own_project: Optional[str] = None) -> "DatasetRef":
        """Parse ``dataset-x@v2``, ``my-repo@main`` or ``<owner>/dataset-x@v2``; DatasetError says what is wrong.

        An owner equal to ``own_project`` is dropped: ``b/dataset-x@v1`` in project ``b`` is ``dataset-x@v1``.
        """
        text = (text or "").strip()
        repo, sep, version = text.partition("@")
        if not sep or not repo or not version:
            raise DatasetError(f"{text!r} is not a dataset reference: write <repository>@<ref>, "
                               f"e.g. dataset-default@v2, dataset-default@{LATEST}, my-repo@main "
                               "or <project>/dataset-default@v2.")
        if "@" in version:
            raise DatasetError(f"{text!r} has more than one '@': write <repository>@<ref>.")
        owner = None
        if "/" in repo:
            owner, _, repo = repo.partition("/")
            _check_shared(text, owner, repo)
        if not _REPO_RE.match(repo):
            raise DatasetError(f"{repo!r} is not a valid lakeFS repository name: use 3 to 63 characters "
                               "from a-z, 0-9 and '-', starting with a letter or digit.")
        if not _REF_RE.match(version) or ".." in version or version.endswith(("/", ".lock")):
            raise DatasetError(f"{version!r} is not a valid ref: use {LATEST}, a version like v2, "
                               "a branch, a tag or a commit id.")
        return cls(repo, version, owner=None if owner == own_project else owner)

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}@{self.version}" if self.owner else f"{self.repo}@{self.version}"


def _check_shared(text: str, owner: str, repo: str) -> None:
    """The ``<owner>/<repo>`` half of a shared reference: a project name and a ``dataset-*`` repository."""
    if "/" in repo:
        raise DatasetError(f"{text!r} has more than one '/': write <project>/dataset-<name>@<version>.")
    if not _OWNER_RE.match(owner):
        raise DatasetError(f"{owner!r} is not a project name: use 1 to 63 characters from a-z, 0-9 and '-', "
                           "starting and ending with a letter or digit.")
    if not repo.startswith(DATASET_PREFIX) or repo == DATASET_PREFIX:
        raise DatasetError(f"{owner}/{repo} is not a shared dataset: another project can share only its "
                           f"{DATASET_PREFIX}<name> repositories, e.g. {owner}/dataset-default@v1.")


def refuse_shared(name: str, action: str) -> None:
    """DatasetError when ``name`` (a repository, a name or a reference) belongs to another project."""
    if "/" in (name or "").partition("@")[0]:
        owner = name.split("/", 1)[0]
        raise DatasetError(f"cannot {action} {name}: it belongs to project {owner}, and datasets shared "
                           f"with your project are read-only. Ask {owner} to {action} it.")


@dataclass
class DatasetInfo:
    """One row of ``list_datasets``: the repository and its labels."""
    repo: str
    description: str = ""
    template: str = ""
    default: bool = False
    location: str = ""
    labels: dict = field(default_factory=dict)
    owner: Optional[str] = None                     # set for a dataset another project shares
    versions: list = field(default_factory=list)    # shared datasets: their tags, newest first


def _client(client: Optional[LakeFS]) -> LakeFS:
    return client or LakeFS.connect()


def source(ref: DatasetRef, client: Optional[LakeFS] = None) -> tuple:
    """``(ref, client)`` that reads ``ref``: the own lakeFS, or the owner's for a shared reference.

    An owner that is the own project is dropped from the returned ref. A client already pointing at the
    owner's lakeFS (``client.owner``) is used as is.
    """
    c = _client(client)
    if not ref.owner or c.owner == ref.owner:
        return ref, c
    if c.owner:
        raise DatasetError(f"{ref} belongs to project {ref.owner}, but this client reads project {c.owner}.")
    from . import peers
    if ref.owner == peers.load(c).project:
        return replace(ref, owner=None), c
    return ref, c.for_owner(ref.owner)


def default_branch(c: LakeFS, repo: str) -> str:
    """The repository's default branch (``main`` when lakeFS does not say)."""
    info = c.repository(repo)
    if info is None:
        raise DatasetError(f"repository {repo} does not exist. List datasets with `kubecore dataset list`.")
    return info.get("default_branch") or MAIN


def _lookup(c: LakeFS, repo: str, name: str) -> Optional[str]:
    """Commit of ``name`` as a branch, then a tag, then a commit id; None when it is none of them."""
    for find in (c.branch_commit, c.tag_commit, c.commit_id):
        try:
            return find(repo, name)
        except NotFoundError:
            continue
    return None


def resolve(ref: DatasetRef, client: Optional[LakeFS] = None, commit: Optional[str] = None) -> str:
    """The commit id ``ref`` points at.

    ``latest`` is the head of the default branch, ``vN`` a tag, anything else a branch, tag or commit id
    (tried in that order). A pinned ``commit`` (argument, or carried by ``ref``) is returned as is,
    with no lakeFS call.
    """
    pinned = commit or ref.commit
    if pinned:
        return ref.with_commit(pinned).commit
    ref, c = source(ref, client)
    branch = default_branch(c, ref.repo)  # also the clear "does not exist" error
    if ref.version == LATEST:
        return c.branch_commit(ref.repo, branch)
    found = _lookup(c, ref.repo, ref.version) if not _VERSION_RE.match(ref.version) else _tag_or_none(c, ref)
    if found:
        return found
    if _VERSION_RE.match(ref.version):
        have = ", ".join(versions(ref.repo, c))
        raise DatasetError(f"{ref.repo} has no version {ref.version}. "
                           f"Available: {have or 'none yet (release one with `kubecore dataset release`)'}.")
    raise DatasetError(f"{ref.repo} has no branch, tag or commit {ref.version!r}.")


def _tag_or_none(c: LakeFS, ref: DatasetRef) -> Optional[str]:
    try:
        return c.tag_commit(ref.repo, ref.version)
    except NotFoundError:
        return None


def format_of(repo: str, client: Optional[LakeFS] = None) -> str:
    """Name of the format a repository is labelled with (``kaos.template``) if we know it, else ``raw``."""
    from .formats import format_names, get_format
    try:
        label = _client(client).metadata(repo).get(LABEL_TEMPLATE)
    except LakeFSError:
        label = None
    known = label and (label in format_names() or label == "yolo")
    return get_format(label).name if known else "raw"


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


def split_owner(name: str) -> tuple:
    """``(owner, repo)`` of ``<owner>/dataset-<name>`` (validated as in a shared reference), else ``(None, name)``."""
    if "/" not in (name or ""):
        return None, name
    owner, _, repo = name.partition("/")
    _check_shared(name, owner, repo)
    return owner, repo


def versions(repo: str, client: Optional[LakeFS] = None) -> list:
    """Version tags of ``repo`` as ``["v1", "v2", ...]`` in numeric order.

    ``<owner>/dataset-<name>`` lists a dataset another project shares, from the owner's lakeFS.
    """
    owner, repo = split_owner(repo)
    _, c = source(DatasetRef(repo, LATEST, owner=owner), client)
    nums = sorted(n for n in (_version_number(t["id"]) for t in c.tags(repo)) if n)
    return [f"v{n}" for n in nums]


def release(repo: str, client: Optional[LakeFS] = None) -> str:
    """Tag the head of the default branch (``main``) with the next ``vN`` and return it (v10 follows v9)."""
    refuse_shared(repo, "release")
    c = _client(client)
    head = c.branch_commit(repo, default_branch(c, repo))
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
    """Storage for a new repository: ``<prefix>/<repo>``, the prefix kaos-lake publishes, else the env base."""
    base = c.storage_namespace_prefix() or os.environ.get(STORAGE_BASE_ENV)
    if not base:
        raise DatasetError(f"cannot choose storage for {repo}: kaos-lake did not publish a storage prefix. "
                           f"Set {STORAGE_BASE_ENV} (e.g. gs://bucket/lakefs).")
    return f"{base.rstrip('/')}/{repo}"


def ensure_repository(c: LakeFS, repo: str, labels: dict) -> bool:
    """Create ``repo`` and set ``labels`` unless it exists; returns True when it was created."""
    if c.repository(repo):
        return False
    c.create_repository(repo, _storage_namespace(c, repo), MAIN)
    c.set_metadata(repo, labels)
    return True


def _create_empty(c: LakeFS, repo: str, description: str) -> str:
    """An empty ``dataset-<name>`` labelled kaos.kind=dataset: no files, no starter commit, no template."""
    if c.repository(repo):
        raise DatasetError(f"{repo} already exists. Push to it with `kubecore dataset push <dir> {repo}`.")
    c.create_repository(repo, _storage_namespace(c, repo), MAIN)
    labels = {LABEL_KIND: "dataset"}
    if description:
        labels[LABEL_DESCRIPTION] = description
    c.set_metadata(repo, labels)
    return repo


def create_dataset(name: str, fmt_name: str = "ultralytics", description: str = "",
                   client: Optional[LakeFS] = None, **skeleton_args) -> str:
    """Create ``dataset-<name>`` the way the kaos-lake UI does; returns the repository name.

    Order: create the repository, commit the format's skeleton to main (commit metadata
    ``kaos.template``), then set the labels. Fails if the repository already exists. ``fmt_name="none"`` creates an empty labelled repository.
    """
    from .formats import get_format
    refuse_shared(name, "create")
    c = _client(client)
    if fmt_name == NO_TEMPLATE:
        return _create_empty(c, dataset_repo(name), description)
    fmt = get_format(fmt_name)
    repo = dataset_repo(name)
    files = fmt.creator.skeleton(description=description, **skeleton_args)
    if c.repository(repo):
        raise DatasetError(f"{repo} already exists. Push to it with `kubecore dataset push <dir> {repo}`.")
    c.create_repository(repo, _storage_namespace(c, repo), MAIN)
    with tempfile.TemporaryDirectory() as tmp:
        for rel, content in files.items():
            target = pathlib.Path(tmp, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        upload_tree(c, repo, MAIN, pathlib.Path(tmp))
    c.commit(repo, MAIN, f"Create {fmt.name} dataset skeleton", {LABEL_TEMPLATE: fmt.name})
    labels = {LABEL_KIND: "dataset", LABEL_TEMPLATE: fmt.name}
    if description:
        labels[LABEL_DESCRIPTION] = description
    c.set_metadata(repo, labels)
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
                 labels: Optional[dict] = None, client: Optional[LakeFS] = None,
                 metadata: Optional[dict] = None) -> PublishResult:
    """Mirror ``local_dir`` into ``repo``: draft branch, commit, pull request into main.

    Creates the repository (with ``labels``) when missing. With
    ``via_pull_request=False`` the commit goes straight to main (admin use only).
    ``metadata`` is recorded on the commit. Raises DatasetError when the directory is identical to main.
    """
    refuse_shared(repo, "push to")
    c, root = _client(client), pathlib.Path(local_dir)
    created = ensure_repository(c, repo, labels or {LABEL_KIND: "dataset"})
    plan = plan_mirror(c, repo, MAIN, root)
    if plan.empty:
        raise DatasetError(f"nothing to publish: {root} is identical to {repo} main.")
    branch = MAIN
    if via_pull_request:
        branch = "draft-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        c.create_branch(repo, branch, MAIN)
    apply_plan(c, repo, branch, plan)
    commit = c.commit(repo, branch, message, metadata)
    if not via_pull_request:
        return PublishResult(repo, created, commit, branch)
    pull_id = c.create_pull(repo, branch, MAIN, message)
    return PublishResult(repo, created, commit, branch, pull_id,
                         f"{c.base_url}/repositories/{repo}/pulls/{pull_id}")


def materialize(ref: DatasetRef, dest=None, fmt_name: Optional[str] = None,
                client: Optional[LakeFS] = None, commit: Optional[str] = None,
                prefix: Optional[str] = None) -> pathlib.Path:
    """Local copy of ``ref`` through its format's consumer.

    Returns the format's entry: ``data.yaml`` for ``ultralytics``, the folder for ``raw``. The format is
    ``fmt_name`` if given, else the repository's ``kaos.template`` label (``yolo`` is an alias), else
    ``raw``. ``commit`` (or ``ref.commit``) pins the exact commit; ``prefix`` (raw only) downloads one folder.
    A shared reference (``<owner>/dataset-x@v1``) is read from the owner's lakeFS and cached apart.
    """
    from .formats import get_format
    ref, c = source(ref, client)
    fmt = get_format(fmt_name) if fmt_name else get_format(format_of(ref.repo, c))
    extra = {"prefix": prefix} if prefix else {}
    return fmt.consumer.materialize(ref, dest, c, commit, **extra)
