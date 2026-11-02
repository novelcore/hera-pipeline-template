"""Thin lakeFS REST client (API v1) for kaos-lake. One class, no business logic.

Authentication comes from ``credentials.resolve``: a bearer token, or an
access-key pair sent as Basic auth. ``for_owner`` returns a client for another
project's lakeFS that carries only a bearer token (``credentials.resolve_peer``).
HTTP failures become ``LakeFSError`` subclasses whose messages tell the user what to do next.
"""
from __future__ import annotations

import pathlib
from typing import Iterator, Optional
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import credentials
from .config import resolve_endpoint
from .errors import AuthError, LakeFSError, NotFoundError

USER_AGENT = "kubecore/0.2"


def _q(value: str) -> str:
    return quote(value, safe="")


def _strs(metadata: Optional[dict]) -> dict:
    return {k: str(v) for k, v in (metadata or {}).items()}


def _is_no_changes(exc: LakeFSError) -> bool:
    """lakeFS answers an empty commit or merge with 400 'no changes'."""
    return exc.status == 400 and "no changes" in str(exc).lower()


def _session(cred: credentials.Credential, pool: int) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=0.5, status_forcelist=[502, 503, 504],
                  allowed_methods=["HEAD", "GET", "PUT", "DELETE"], raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool, pool_maxsize=pool)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers["User-Agent"] = USER_AGENT
    if cred.token:
        s.headers["Authorization"] = f"Bearer {cred.token}"
    else:
        s.auth = (cred.access_key, cred.secret_key)
    return s


class LakeFS:
    """A lakeFS server reachable at ``base_url`` with one credential.

    ``owner`` is None for the own project's lakeFS, else the project whose lakeFS this is.
    """

    def __init__(self, base_url: str, credential: credentials.Credential,
                 session: Optional[requests.Session] = None, timeout: int = 300, concurrency: int = 16,
                 owner: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.concurrency = concurrency
        self.owner = owner
        self.session = session or _session(credential, concurrency * 2)
        self._peer_clients: dict = {}

    @classmethod
    def connect(cls, url: Optional[str] = None, start: Optional[str] = None) -> "LakeFS":
        """Resolve the endpoint and the credential chain and return a ready client."""
        base = resolve_endpoint(url, start)
        return cls(base, credentials.resolve(base))

    def for_owner(self, owner: str) -> "LakeFS":
        """A client for the lakeFS of project ``owner`` (this client when ``owner`` is the own project).

        The address comes from the own lakeFS's peers (``/kaos/v1/peers``): the in-cluster endpoint when
        this client's base is an in-cluster ``.svc`` address, else the public URL. The credential is a
        bearer token (``credentials.resolve_peer``), never this project's access key.
        """
        from . import peers
        if self.owner:
            raise LakeFSError(f"this client reads project {self.owner}; ask the own project's client for {owner}.")
        if owner in self._peer_clients:
            return self._peer_clients[owner]
        if owner == peers.load(self).project:
            return self
        base = peers.base_for(self.base_url, peers.peer(self, owner))
        client = LakeFS(base, credentials.resolve_peer(self.base_url), timeout=self.timeout,
                        concurrency=self.concurrency, owner=owner)
        self._peer_clients[owner] = client
        return client

    # -- plumbing --------------------------------------------------------
    def _call(self, method: str, path: str, ok=(200, 201, 204), what: str = "", **kw):
        kw.setdefault("timeout", self.timeout)
        kw.setdefault("allow_redirects", method == "GET")
        resp = self.session.request(method, f"{self.base_url}/api/v1{path}", **kw)
        if resp.status_code in ok:
            return resp
        raise self._error(resp, what or f"{method} {path}")

    def _error(self, resp: requests.Response, what: str) -> LakeFSError:
        status, detail = resp.status_code, (resp.text or "")[:300]
        if self.owner and status in (301, 302, 303, 307, 308, 401, 403):
            return AuthError(f"not shared with your project: project {self.owner}'s lakeFS refused it ({what}). "
                             f"Ask {self.owner} to share the dataset with your project.")
        if status in (301, 302, 303, 307, 308, 401):
            return AuthError(f"lakeFS rejected the credential ({what}). Run `kubecore login` again.")
        if status == 403:
            return AuthError(f"you are not allowed to do this ({what}): {detail}")
        if status == 404:
            return NotFoundError(f"not found ({what}): {detail}", status)
        return LakeFSError(f"{what} failed: HTTP {status} {detail}", status)

    def _pages(self, path: str, params: Optional[dict] = None) -> Iterator[dict]:
        after = ""
        while True:
            body = self._call("GET", path, params={**(params or {}), "after": after, "amount": 1000}).json()
            yield from body.get("results", [])
            page = body.get("pagination", {})
            if not page.get("has_more"):
                return
            after = page.get("next_offset", "")

    # -- repositories ----------------------------------------------------
    def repositories(self) -> list:
        """Every repository the caller may see: dicts with ``id``, ``storage_namespace``, ..."""
        return list(self._pages("/repositories"))

    def repository(self, repo: str) -> Optional[dict]:
        """The repository dict, or None when it does not exist."""
        try:
            return self._call("GET", f"/repositories/{_q(repo)}", what=f"repository {repo}").json()
        except NotFoundError:
            return None

    def create_repository(self, repo: str, storage_namespace: str, default_branch: str = "main") -> None:
        self._call("POST", f"/repositories", json={
            "name": repo, "storage_namespace": storage_namespace, "default_branch": default_branch},
            what=f"create repository {repo}")

    def metadata(self, repo: str) -> dict:
        """The repository's metadata labels (``kaos.*``); lakeFS answers them as a flat object."""
        return self._call("GET", f"/repositories/{_q(repo)}/metadata", what=f"metadata of {repo}").json() or {}

    def set_metadata(self, repo: str, labels: dict) -> None:
        self._call("POST", f"/repositories/{_q(repo)}/metadata", json={"metadata": labels},
                   what=f"set metadata of {repo}")

    # -- refs ------------------------------------------------------------
    def branch_commit(self, repo: str, branch: str) -> str:
        """The commit id at the head of ``branch``."""
        return self._call("GET", f"/repositories/{_q(repo)}/branches/{_q(branch)}",
                          what=f"branch {branch} of {repo}").json()["commit_id"]

    def create_branch(self, repo: str, name: str, source: str) -> None:
        self._call("POST", f"/repositories/{_q(repo)}/branches", json={"name": name, "source": source},
                   what=f"create branch {name}")

    def delete_branch(self, repo: str, name: str) -> None:
        """Delete ``name`` (a missing branch is fine)."""
        self._call("DELETE", f"/repositories/{_q(repo)}/branches/{_q(name)}", ok=(200, 204, 404),
                   what=f"delete branch {name}")

    def merge(self, repo: str, source: str, destination: str, message: str, metadata: Optional[dict] = None,
              tolerate_empty: bool = False) -> str:
        """Merge ``source`` into ``destination`` (mergeIntoBranch); returns the merge commit id.

        With ``tolerate_empty`` a merge with nothing to merge is a success returning the destination head.
        """
        try:
            resp = self._call("POST", f"/repositories/{_q(repo)}/refs/{_q(source)}/merge/{_q(destination)}",
                              json={"message": message, "metadata": _strs(metadata)},
                              what=f"merge {source} into {destination}")
        except LakeFSError as exc:
            if tolerate_empty and _is_no_changes(exc):
                return self.branch_commit(repo, destination)
            raise
        return resp.json()["reference"]

    def branch_exists(self, repo: str, branch: str) -> bool:
        try:
            self.branch_commit(repo, branch)
            return True
        except NotFoundError:
            return False

    def storage_namespace_prefix(self) -> Optional[str]:
        """Where kaos-lake wants new repositories (``GET /kaos/v1/dataset-templates``), or None if it does not say."""
        try:
            resp = self.session.get(f"{self.base_url}/kaos/v1/dataset-templates", timeout=30, allow_redirects=False)
            return (resp.json().get("storage_namespace_prefix") or None) if resp.status_code == 200 else None
        except (requests.RequestException, ValueError):
            return None

    def tags(self, repo: str) -> list:
        """Every tag: dicts with ``id`` (name) and ``commit_id``."""
        return list(self._pages(f"/repositories/{_q(repo)}/tags"))

    def tag_commit(self, repo: str, tag: str) -> str:
        return self._call("GET", f"/repositories/{_q(repo)}/tags/{_q(tag)}",
                          what=f"tag {tag} of {repo}").json()["commit_id"]

    def commit_id(self, repo: str, commit: str) -> str:
        """``commit`` itself when it exists in ``repo`` (NotFoundError otherwise)."""
        return self._call("GET", f"/repositories/{_q(repo)}/commits/{_q(commit)}",
                          what=f"commit {commit} of {repo}").json()["id"]

    def create_tag(self, repo: str, tag: str, ref: str) -> None:
        self._call("POST", f"/repositories/{_q(repo)}/tags", json={"id": tag, "ref": ref},
                   what=f"create tag {tag}")

    # -- objects ---------------------------------------------------------
    def list_objects(self, repo: str, ref: str, prefix: str = "") -> Iterator[dict]:
        """Every object under ``prefix`` on ``ref``: dicts with ``path``, ``checksum``, ``size_bytes``."""
        for obj in self._pages(f"/repositories/{_q(repo)}/refs/{_q(ref)}/objects/ls", {"prefix": prefix}):
            if obj.get("path_type", "object") == "object":
                yield obj

    def download_object(self, repo: str, ref: str, path: str, dest: pathlib.Path) -> None:
        """Stream one object at ``ref`` (a commit id pins it) to ``dest``."""
        resp = self._call("GET", f"/repositories/{_q(repo)}/refs/{_q(ref)}/objects",
                          params={"path": path}, stream=True, what=f"download {path}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)

    def upload_object(self, repo: str, branch: str, path: str, local: pathlib.Path) -> None:
        with local.open("rb") as fh:
            self._call("POST", f"/repositories/{_q(repo)}/branches/{_q(branch)}/objects",
                       params={"path": path}, files={"content": (local.name, fh)}, what=f"upload {path}")

    def delete_object(self, repo: str, branch: str, path: str) -> None:
        self._call("DELETE", f"/repositories/{_q(repo)}/branches/{_q(branch)}/objects",
                   params={"path": path}, ok=(200, 204, 404), what=f"delete {path}")

    def commit(self, repo: str, branch: str, message: str, metadata: Optional[dict] = None,
               tolerate_empty: bool = False) -> str:
        """Commit the staged changes on ``branch``; returns the new commit id.

        With ``tolerate_empty`` a commit with nothing staged is a success returning the branch head.
        """
        try:
            resp = self._call("POST", f"/repositories/{_q(repo)}/branches/{_q(branch)}/commits",
                              json={"message": message, "metadata": _strs(metadata)}, what=f"commit on {branch}")
        except LakeFSError as exc:
            if tolerate_empty and _is_no_changes(exc):
                return self.branch_commit(repo, branch)
            raise
        return resp.json()["id"]

    # -- pull requests ---------------------------------------------------
    def create_pull(self, repo: str, source: str, destination: str, title: str, description: str = "") -> str:
        """Open a pull request source -> destination; returns its id."""
        resp = self._call("POST", f"/repositories/{_q(repo)}/pulls", json={
            "title": title, "description": description,
            "source_branch": source, "destination_branch": destination}, what="open pull request")
        return str(resp.json()["id"])
