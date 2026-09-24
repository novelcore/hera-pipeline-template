"""Thin lakeFS REST client used by the dataset CLI.

lakeFS OSS runs here in ``basic_auth`` mode (RBAC:none): a single admin user, no
per-user identity, and no mintable per-user credentials. On this platform lakeFS
sits behind oauth2-proxy(Zitadel) + an nginx sidecar that injects the shared
admin Basic-auth header server-side. oauth2-proxy is the gate: it accepts only a
valid ``_lakefs_oauth2`` session cookie (or a Zitadel JWT bearer) and rejects a
raw admin Basic header, so the admin key is useless to a headless caller. The
credential the CLI carries is therefore the session cookie — oauth2-proxy
validates it and forwards to nginx, which injects admin Basic before lakeFS.
This client carries only that cookie; no lakeFS access keys ever live on the
developer's machine. (See login.py for how the cookie is captured same-origin.)

Everything talks to the SSO-protected ingress `https://lakefs-<project>.<baseDns>`
over the lakeFS REST API v1. See ``dataset_tools/README.md`` for the full flow.
"""
from __future__ import annotations

import pathlib
from typing import Iterator, Optional
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

COOKIE_NAME = "_lakefs_oauth2"
USER_AGENT = "kubecore-dataset-cli/1.0"


class LakeFSError(RuntimeError):
    """A lakeFS API call failed (non-2xx) or auth is invalid."""


class LakeFSClient:
    """Cookie-authenticated lakeFS REST client over the SSO ingress."""

    def __init__(self, base_url: str, cookie: Optional[str] = None,
                 concurrency: int = 16, timeout: int = 300,
                 token: Optional[str] = None):
        """Authenticate with a Zitadel bearer ``token`` (preferred) or a session
        ``cookie`` (legacy paste path).

        Bearer is preferred: it is a per-user, short-lived, audience-scoped
        Zitadel token obtained via the browser login, where the cookie is a 4h session
        that had to be copied out of a browser by hand. oauth2-proxy accepts
        both — ``--skip-jwt-bearer-tokens=true`` verifies a bearer against
        Zitadel's JWKS and forwards to the nginx sidecar exactly as it does for
        a cookie session.
        """
        if not token and not cookie:
            raise LakeFSError("LakeFSClient needs either a bearer token or a session cookie")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = self._make_session(cookie, concurrency, token)

    # -- session ---------------------------------------------------------
    @staticmethod
    def _make_session(cookie: Optional[str], concurrency: int,
                      token: Optional[str] = None) -> requests.Session:
        s = requests.Session()
        retry = Retry(
            total=5,
            backoff_factor=0.5,
            status_forcelist=[502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=concurrency * 2,
            pool_maxsize=concurrency * 2,
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update({"User-Agent": USER_AGENT})
        if token:
            s.headers["Authorization"] = f"Bearer {token}"
        elif cookie:
            s.cookies.set(COOKIE_NAME, cookie)
        return s

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v1{path}"

    # -- auth / existence ------------------------------------------------
    def check_auth(self) -> bool:
        """Return True iff the carried credential authenticates.

        oauth2-proxy answers a bad/expired credential with a 302 to the login
        page, so we disable redirects and require a 200.
        """
        r = self.session.get(
            self._url("/repositories"),
            params={"amount": 1},
            timeout=30,
            allow_redirects=False,
        )
        return r.status_code == 200

    def branch_exists(self, repo: str, branch: str) -> bool:
        r = self.session.get(
            self._url(f"/repositories/{repo}/branches/{quote(branch, safe='')}"),
            timeout=30,
            allow_redirects=False,
        )
        return r.status_code == 200

    def ensure_branch(self, repo: str, branch: str, source: str) -> None:
        """Create ``branch`` from ``source`` if it doesn't exist (idempotent)."""
        if self.branch_exists(repo, branch):
            return
        r = self.session.post(
            self._url(f"/repositories/{repo}/branches"),
            json={"name": branch, "source": source},
            timeout=60,
            allow_redirects=False,
        )
        if r.status_code not in (201, 409):
            raise LakeFSError(
                f"create branch {branch} from {source} failed: "
                f"HTTP {r.status_code} {r.text[:300]}"
            )

    def default_branch(self, repo: str) -> str:
        r = self.session.get(
            self._url(f"/repositories/{quote(repo, safe='')}"),
            timeout=30,
            allow_redirects=False,
        )
        if r.status_code != 200:
            raise LakeFSError(
                f"repository {repo} not found: HTTP {r.status_code} {r.text[:200]}"
            )
        return r.json().get("default_branch", "main")

    # -- listing ---------------------------------------------------------
    def list_objects(self, repo: str, ref: str, prefix: str = "") -> Iterator[dict]:
        """Yield every object under ``prefix`` on ``ref`` (paginated).

        Each dict carries at least ``path``, ``checksum`` and ``size_bytes``.
        Uses ``&user_metadata=false`` and a large page size to minimise calls.
        """
        after = ""
        while True:
            r = self.session.get(
                self._url(f"/repositories/{repo}/refs/{quote(ref, safe='')}/objects/ls"),
                params={"prefix": prefix, "after": after, "amount": 1000},
                timeout=120,
                allow_redirects=False,
            )
            if r.status_code != 200:
                raise LakeFSError(
                    f"list objects on {repo}@{ref} failed: "
                    f"HTTP {r.status_code} {r.text[:300]}"
                )
            body = r.json()
            for obj in body.get("results", []):
                # skip common-prefix "directory" entries (path_type != object)
                if obj.get("path_type", "object") == "object":
                    yield obj
            pagination = body.get("pagination", {})
            if not pagination.get("has_more"):
                return
            after = pagination.get("next_offset", "")

    # -- mutation --------------------------------------------------------
    def upload_object(self, repo: str, branch: str, path: str,
                      local: pathlib.Path) -> None:
        url = self._url(
            f"/repositories/{repo}/branches/{quote(branch, safe='')}"
            f"/objects?path={quote(path, safe='')}"
        )
        with local.open("rb") as fh:
            r = self.session.post(
                url,
                files={"content": (local.name, fh, "application/octet-stream")},
                timeout=self.timeout,
                allow_redirects=False,
            )
        if r.status_code not in (200, 201):
            raise LakeFSError(f"{path}: upload HTTP {r.status_code} {r.text[:200]}")

    def delete_object(self, repo: str, branch: str, path: str) -> None:
        url = self._url(
            f"/repositories/{repo}/branches/{quote(branch, safe='')}"
            f"/objects?path={quote(path, safe='')}"
        )
        r = self.session.delete(url, timeout=60, allow_redirects=False)
        # 204 = deleted, 404 = already gone (idempotent)
        if r.status_code not in (204, 404):
            raise LakeFSError(f"{path}: delete HTTP {r.status_code} {r.text[:200]}")

    def commit(self, repo: str, branch: str, message: str,
               metadata: Optional[dict] = None) -> Optional[str]:
        """Commit staged changes on ``branch``. Returns the commit id.

        Treats "nothing to commit" (400 with that reason) as a no-op success,
        returning the current branch tip commit id.
        """
        r = self.session.post(
            self._url(f"/repositories/{repo}/branches/{quote(branch, safe='')}/commits"),
            json={"message": message, "metadata": {k: str(v) for k, v in (metadata or {}).items()}},
            timeout=600,
            allow_redirects=False,
        )
        if r.status_code in (200, 201):
            return r.json().get("id")
        if r.status_code == 400 and "no changes" in r.text.lower():
            return self.branch_tip(repo, branch)
        raise LakeFSError(f"commit failed: HTTP {r.status_code} {r.text[:400]}")

    def branch_tip(self, repo: str, branch: str) -> Optional[str]:
        r = self.session.get(
            self._url(f"/repositories/{repo}/branches/{quote(branch, safe='')}"),
            timeout=30,
            allow_redirects=False,
        )
        if r.status_code != 200:
            return None
        return r.json().get("commit_id")
