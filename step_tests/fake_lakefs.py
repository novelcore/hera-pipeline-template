# Vendored from kaos-io/kaos-lib tests/fake_lakefs.py at dc24f292029bb2a49a2cdf5c24eb169d7706d9a5 (test fake only, never in step images).
# Re-vendor it when the template's kaos-lib pin (KAOS_LIB_PACKAGE in steps/*/Dockerfile) moves.
"""In-memory lakeFS for tests: a requests transport adapter, so the real client code runs unchanged."""
from __future__ import annotations

import hashlib
import io
import itertools
import json
import re
from email.parser import BytesParser
from urllib.parse import parse_qs, unquote, urlsplit

import requests
from requests.adapters import BaseAdapter

from kaos_lib import credentials, lakefs
from kaos_lib.lakefs import LakeFS

BRANCH_ID = re.compile(r"^\w[-\w]*$")  # lakeFS's branch id rule


class FakeLakeFS(BaseAdapter):
    """Repos with branches (committed + staged), commits, tags, metadata and pulls."""

    BASE = "http://lakefs.test"

    def __init__(self, base: str = BASE):
        super().__init__()
        self.base = base
        self.repos: dict = {}
        self.calls: list = []        # (method, path-without-query)
        self.auth: list = []         # the Authorization header of every request (None when absent)
        self.kaos: dict = {}         # "/kaos/v1/..." -> (status, JSON body or raw bytes); others: 404 HTML
        self.deny = None             # an HTTP status every /api/v1 call answers (a token this server refuses)
        self.writes: list = []       # (kind, repo, branch, path) for object uploads/deletes
        self.storage_prefix = "gs://bucket/lakefs"   # None: kaos-lake publishes no prefix
        self._ids = itertools.count(1)

    # ---- test helpers
    def add_repo(self, name, ns="gs://bucket/proj/seed", metadata=None, files=None):
        commit = self._new_commit(name, files or {})
        self.repos[name] = {"ns": ns, "metadata": dict(metadata or {}), "commits": {commit[0]: commit[1]},
                            "branches": {"main": {"commit": commit[0], "staged": {}}},
                            "tags": {}, "pulls": []}
        return commit[0]

    def _new_commit(self, repo, objects):
        cid = f"c{next(self._ids):04d}" + "0" * 8
        if repo in self.repos:
            self.repos[repo]["commits"][cid] = dict(objects)
        return cid, dict(objects)

    def tag(self, repo, name, ref="main"):
        self.repos[repo]["tags"][name] = self._resolve(repo, ref)

    def head(self, repo, branch="main"):
        return self.repos[repo]["branches"][branch]["commit"]

    def tree(self, repo, ref):
        return self._view(repo, ref)

    def client(self, bearer="t", credential=None):
        """A real client (real session code, so real auth headers) whose every request reaches this fake."""
        cred = credential or credentials.Credential(token=bearer)
        s = lakefs._session(cred, 8)
        s.mount("http://", self)
        s.mount("https://", self)
        return LakeFS(self.base, cred, session=s, concurrency=4)

    # ---- state
    def _resolve(self, repo, ref):
        r = self.repos[repo]
        if ref in r["branches"]:
            return r["branches"][ref]["commit"]
        if ref in r["tags"]:
            return r["tags"][ref]
        if ref in r["commits"]:
            return ref
        raise KeyError(ref)

    def _view(self, repo, ref):
        r = self.repos[repo]
        if ref in r["branches"]:
            b = r["branches"][ref]
            view = dict(r["commits"][b["commit"]])
            for p, c in b["staged"].items():
                if c is None:
                    view.pop(p, None)
                else:
                    view[p] = c
            return view
        return dict(r["commits"][self._resolve(repo, ref)])

    # ---- transport
    def send(self, request, **kwargs):
        u = urlsplit(request.url)
        path, q = u.path.removeprefix("/api/v1"), {k: v[0] for k, v in parse_qs(u.query).items()}
        self.calls.append((request.method, path))
        self.auth.append(request.headers.get("Authorization"))
        try:
            if self.deny and not path.startswith("/kaos/"):
                raise PermissionError
            status, body = self._route(request, path, q)
        except PermissionError:
            status, body = self.deny, {"message": "insufficient permissions"}
        except KeyError:
            status, body = 404, {"message": "not found"}
        resp = requests.Response()
        resp.status_code = status
        resp.url = request.url
        raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        resp.raw = io.BytesIO(raw)
        resp._content = raw
        resp.request = request
        return resp

    def close(self):
        pass

    def _route(self, req, path, q):
        if path == "/kaos/v1/dataset-templates":
            if self.storage_prefix is None:
                return 404, {}
            return 200, {"storage_namespace_prefix": self.storage_prefix, "templates": []}
        if path.startswith("/kaos/"):
            return self.kaos.get(path, (404, b"<html><body>404 page not found</body></html>"))
        m, body = req.method, (json.loads(req.body) if req.body and not _is_multipart(req) else {})
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if parts == ["repositories"]:
            if m == "GET":
                return 200, {"results": [{"id": n, "storage_namespace": r["ns"]} for n, r in sorted(self.repos.items())],
                             "pagination": {"has_more": False}}
            self.add_repo(body["name"], body["storage_namespace"])
            self.repos[body["name"]]["metadata"] = {}
            return 201, {"id": body["name"]}
        repo, rest = parts[1], parts[2:]
        if repo not in self.repos:
            return 404, {"message": "repository not found"}
        r = self.repos[repo]
        if not rest:
            return 200, {"id": repo, "storage_namespace": r["ns"], "default_branch": r.get("default_branch", "main")}
        return self._repo_route(m, repo, r, rest, body, q, req)

    def _repo_route(self, m, repo, r, rest, body, q, req):
        kind = rest[0]
        if kind == "metadata":
            if m == "GET":
                return 200, dict(r["metadata"])  # lakeFS: a flat object, not {"metadata": ...}
            r["metadata"].update(body["metadata"])
            return 204, None
        if kind == "branches":
            return self._branches(m, repo, r, rest[1:], body, req, q)
        if kind == "commits":
            return (200, {"id": rest[1]}) if rest[1] in r["commits"] else (404, {})
        if kind == "tags":
            if len(rest) == 1 and m == "GET":
                return 200, {"results": [{"id": t, "commit_id": c} for t, c in sorted(r["tags"].items())],
                             "pagination": {"has_more": False}}
            if len(rest) == 1:
                r["tags"][body["id"]] = self._resolve(repo, body["ref"])
                return 201, {"id": body["id"], "commit_id": r["tags"][body["id"]]}
            return 200, {"id": rest[1], "commit_id": r["tags"][rest[1]]}
        if kind == "refs" and rest[2] == "merge":
            return self._merge(r, rest[1], rest[3], body)
        if kind == "refs":
            return self._refs(repo, rest[1], rest[2:], q)
        if kind == "pulls":
            pid = str(len(r["pulls"]) + 1)
            r["pulls"].append({"id": pid, **body})
            return 201, {"id": pid}
        return 404, {}

    def _branches(self, m, repo, r, rest, body, req, q):
        if not rest:
            if not BRANCH_ID.match(body["name"]):  # lakeFS refuses any other branch id
                return 400, {"message": "argument branch: branch id: invalid value: validation error"}
            base = self._resolve(repo, body["source"])
            r["branches"][body["name"]] = {"commit": base, "base": base, "staged": {}}
            return 201, body["name"]
        b = r["branches"][rest[0]]
        if len(rest) == 1 and m == "DELETE":
            del r["branches"][rest[0]]
            return 204, None
        if len(rest) == 1:
            return 200, {"id": rest[0], "commit_id": b["commit"]}
        if rest[1] == "objects":
            self.writes.append((m, repo, rest[0], q["path"]))
            if m == "POST":
                b["staged"][q["path"]] = _multipart_content(req)
                r.setdefault("mtimes", {})[q["path"]] = next(self._ids)   # write order stands in for mtime
            else:
                b["staged"][q["path"]] = None
            return (201 if m == "POST" else 204), {}
        if rest[1] == "commits":
            view = self._view(repo, rest[0])
            if view == r["commits"][b["commit"]]:
                return 400, {"message": "commit: no changes"}
            cid, _ = self._new_commit(repo, view)
            r["commits"][cid] = view
            b.update(commit=cid, staged={})
            r.setdefault("commit_log", []).append((rest[0], cid, body["message"], body.get("metadata", {})))
            return 201, {"id": cid}
        return 404, {}

    def _merge(self, r, source, dest, body):
        """Three-way merge of a branch into dest: dest's tree plus the branch's changes since its base."""
        src, dst = r["branches"][source], r["branches"][dest]
        base, head = r["commits"][src["base"]], r["commits"][src["commit"]]
        tree = dict(r["commits"][dst["commit"]])
        for path in set(base) | set(head):
            if head.get(path) == base.get(path):
                continue
            if path in head:
                tree[path] = head[path]
            else:
                tree.pop(path, None)
        if tree == r["commits"][dst["commit"]]:
            return 400, {"message": "merge: no changes"}
        repo = next(n for n, x in self.repos.items() if x is r)
        cid, _ = self._new_commit(repo, tree)
        dst["commit"] = cid
        r.setdefault("commit_log", []).append((dest, cid, body["message"], body.get("metadata", {})))
        return 200, {"reference": cid}

    def _refs(self, repo, ref, rest, q):
        view = self._view(repo, ref)
        if rest[0] == "objects" and len(rest) == 2:  # objects/ls
            pre = q.get("prefix", "")
            return 200, {"results": [{"path": p, "path_type": "object", "size_bytes": len(c), "mtime": self.repos[repo].get("mtimes", {}).get(p, 0),
                                      "checksum": hashlib.md5(c).hexdigest()}
                                     for p, c in sorted(view.items()) if p.startswith(pre)],
                         "pagination": {"has_more": False}}
        return 200, view[q["path"]]  # objects?path=


def _is_multipart(req):
    return "multipart" in (req.headers.get("Content-Type") or "")


def _multipart_content(req) -> bytes:
    raw = b"Content-Type: " + req.headers["Content-Type"].encode() + b"\r\n\r\n" + req.body
    for part in BytesParser().parsebytes(raw).get_payload():
        return part.get_payload(decode=True) or b""
    return b""
