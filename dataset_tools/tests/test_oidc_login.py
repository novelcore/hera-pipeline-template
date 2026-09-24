"""oidc_login tests: authorization code + PKCE on a loopback redirect.

The end-to-end tests run the real local callback server; only the browser and
Zitadel's token endpoint are faked. The fake browser plays Zitadel's part: it
reads the authorize URL the CLI opened and sends the redirect to its
redirect_uri, exactly as Zitadel would after the user signs in.
"""
from __future__ import annotations

import base64
import hashlib
import threading
import urllib.parse
import urllib.request

import pytest

from dataset_cli import oidc_login

ENDPOINTS = {"authorization_endpoint": "https://z.example/oauth/v2/authorize",
             "token_endpoint": "https://z.example/oauth/v2/token"}


def _challenge_of(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _fake_browser(monkeypatch, redirect_params):
    """Replace webbrowser.open with 'Zitadel redirects back to the CLI'.

    redirect_params(query) -> dict of params to send to redirect_uri, given the
    authorize request's query (so tests can echo or tamper with state).
    """
    seen = {}

    def open_(url):
        query = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}
        seen.update(query)
        target = query["redirect_uri"] + "?" + urllib.parse.urlencode(redirect_params(query))
        threading.Thread(target=lambda: urllib.request.urlopen(target, timeout=5).read(),
                         daemon=True).start()
        return True

    monkeypatch.setattr(oidc_login.webbrowser, "open", open_)
    monkeypatch.setattr(oidc_login, "discover_endpoints", lambda issuer: ENDPOINTS)
    return seen


def test_pkce_pair_is_rfc7636_s256():
    verifier, challenge = oidc_login.make_pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == _challenge_of(verifier)
    assert "=" not in challenge


def test_authorize_url_is_public_pkce_with_project_audience():
    url = oidc_login.build_authorize_url(
        ENDPOINTS["authorization_endpoint"], "cid", "http://127.0.0.1:5555/callback",
        "chal", "st", audience_project_id="proj-9")
    q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}
    assert q["response_type"] == "code"
    assert q["code_challenge_method"] == "S256"
    assert q["redirect_uri"] == "http://127.0.0.1:5555/callback"
    # Without the project-audience scope oauth2-proxy rejects the token.
    assert "urn:zitadel:iam:org:project:id:proj-9:aud" in q["scope"]
    # A public client sends no secret — that is the whole point of the app shape.
    assert "client_secret" not in q


def test_login_round_trip_exchanges_code_with_matching_verifier(monkeypatch):
    seen = _fake_browser(monkeypatch, lambda q: {"code": "the-code", "state": q["state"]})
    exchanged = {}

    def fake_exchange(token_endpoint, client_id, code, redirect_uri, verifier, timeout=30):
        exchanged.update(code=code, redirect_uri=redirect_uri, verifier=verifier,
                         client_id=client_id)
        return {"access_token": "tok"}

    monkeypatch.setattr(oidc_login, "exchange_code", fake_exchange)
    tokens = oidc_login.login("https://z.example", "cid", audience_project_id="p", timeout=10)

    assert tokens == {"access_token": "tok"}
    assert exchanged["code"] == "the-code"
    # The verifier sent to the token endpoint must be the one whose challenge
    # went out in the authorize request, or Zitadel refuses the exchange.
    assert _challenge_of(exchanged["verifier"]) == seen["code_challenge"]
    # redirect_uri must match the authorize request byte for byte.
    assert exchanged["redirect_uri"] == seen["redirect_uri"]
    # Loopback on 127.0.0.1, on whatever port the OS gave us.
    assert seen["redirect_uri"].startswith("http://127.0.0.1:")
    assert seen["redirect_uri"].endswith("/callback")


def test_state_mismatch_refuses_the_code(monkeypatch):
    _fake_browser(monkeypatch, lambda q: {"code": "c", "state": "not-ours"})
    monkeypatch.setattr(oidc_login, "exchange_code",
                        lambda *a, **k: pytest.fail("exchanged a code with the wrong state"))
    with pytest.raises(oidc_login.LoginError, match="state"):
        oidc_login.login("https://z.example", "cid", timeout=10)


def test_error_redirect_is_reported(monkeypatch):
    _fake_browser(monkeypatch, lambda q: {"error": "access_denied", "state": q["state"]})
    with pytest.raises(oidc_login.LoginError, match="access_denied"):
        oidc_login.login("https://z.example", "cid", timeout=10)


def test_times_out_when_the_browser_never_comes_back(monkeypatch):
    monkeypatch.setattr(oidc_login.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(oidc_login, "discover_endpoints", lambda issuer: ENDPOINTS)
    with pytest.raises(oidc_login.LoginError, match="timed out"):
        oidc_login.login("https://z.example", "cid", timeout=1)


def test_default_timeout_budgets_a_human_signin():
    """Regression: the wait once defaulted to 10s and expired while the user was
    still typing their password."""
    assert oidc_login.LOGIN_TIMEOUT >= 120


def test_exchange_code_surfaces_rejection(monkeypatch):
    class R:
        def json(self):
            return {"error": "invalid_grant", "error_description": "code verifier mismatch"}

    monkeypatch.setattr(oidc_login.requests, "post", lambda *a, **k: R())
    with pytest.raises(oidc_login.LoginError, match="invalid_grant"):
        oidc_login.exchange_code("https://z/t", "cid", "c", "http://127.0.0.1:1/callback", "v")


def test_discovery_requires_both_endpoints(monkeypatch):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"token_endpoint": "https://z/t"}

    monkeypatch.setattr(oidc_login.requests, "get", lambda *a, **k: R())
    with pytest.raises(oidc_login.LoginError, match="authorization and token endpoints"):
        oidc_login.discover_endpoints("https://z.example")
