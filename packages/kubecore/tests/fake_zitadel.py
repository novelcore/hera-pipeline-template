"""A fake Zitadel token endpoint: a requests transport adapter that records each token request."""
from __future__ import annotations

import io
import json
from urllib.parse import parse_qs

import requests
from requests.adapters import BaseAdapter


class FakeTokenEndpoint(BaseAdapter):
    """Answers POST /oauth/v2/token with ``status`` and ``body`` (JSON, or raw bytes)."""

    def __init__(self, status: int = 200, body=None):
        super().__init__()
        self.status = status
        self.body = body if body is not None else {"access_token": "minted-token", "token_type": "Bearer",
                                                   "expires_in": 43199}
        self.requests: list = []   # (method, url, form fields)

    def send(self, request, **kwargs):
        body = request.body.decode() if isinstance(request.body, bytes) else (request.body or "")
        self.requests.append((request.method, request.url, {k: v[0] for k, v in parse_qs(body).items()}))
        raw = self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()
        resp = requests.Response()
        resp.status_code, resp.url, resp.request = self.status, request.url, request
        resp.raw, resp._content = io.BytesIO(raw), raw
        return resp

    def close(self):
        pass
