"""A tiny in-process lakeFS HTTP server for the checkpoint helper tests (stdlib only).

Implements only the calls kubecore/checkpoint_helper.py makes: branch get/create, object upload
(multipart), download, stat, list and delete on one repository. Objects are staged on the branch.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class FakeLakeFS:
    def __init__(self, repo="outputs-app"):
        self.repo = repo
        self.branches = {"main": {}}
        self.calls = []
        self.server = None

    def start(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body=b"", ctype="application/json"):
                if not isinstance(body, bytes):
                    body = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _route(self):
                url = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
                parts = url.path.split("/")      # ['', 'api', 'v1', 'repositories', repo, ...]
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                fake.calls.append((self.command, "/".join(parts[5:]), self.headers.get("Authorization")))
                if parts[4] != fake.repo:
                    return self._send(404, {"message": "repository not found"})
                rest = parts[5:]
                if rest[0] == "branches" and len(rest) == 1 and self.command == "POST":
                    name = json.loads(body)["name"]
                    if name in fake.branches:
                        return self._send(409, {})
                    fake.branches[name] = dict(fake.branches[json.loads(body)["source"]])
                    return self._send(201, name.encode(), "text/plain")
                if rest[0] == "branches" and len(rest) == 2:
                    return self._send(200 if rest[1] in fake.branches else 404, {})
                branch = fake.branches.get(rest[1])
                if branch is None:
                    return self._send(404, {})
                return fake.objects(self, branch, rest[2:], query, body)

            do_GET = do_POST = do_DELETE = _route

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def objects(self, h, branch, rest, q, body):
        path = q.get("path", "")
        if rest == ["objects"] and h.command == "POST":
            start = body.index(b"\r\n\r\n") + 4
            end = body.rindex(b"\r\n--")
            branch[path] = (body[start:end], time.time())
            return h._send(201, {"path": path})
        if rest == ["objects"] and h.command == "DELETE":
            branch.pop(path, None)
            return h._send(204)
        if rest == ["objects"]:
            return h._send(200, branch[path][0], "application/octet-stream") if path in branch else h._send(404, {})
        if rest == ["objects", "stat"]:
            return h._send(200, {"size_bytes": len(branch[path][0])}) if path in branch else h._send(404, {})
        if rest == ["objects", "ls"]:
            names = sorted(p for p in branch if p.startswith(q.get("prefix", "")) and p > q.get("after", ""))
            results = [{"path": p, "path_type": "object", "size_bytes": len(branch[p][0]), "mtime": int(branch[p][1])}
                       for p in names[:2]]    # two per page: exercises pagination
            more = len(names) > 2
            return h._send(200, {"results": results, "pagination": {"has_more": more,
                                                                      "next_offset": results[-1]["path"] if results else ""}})
        return h._send(404, {})
