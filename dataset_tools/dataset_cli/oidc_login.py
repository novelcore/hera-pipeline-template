"""Browser login to Zitadel: authorization code + PKCE on a loopback redirect.

This is RFC 8252, the flow `gcloud auth login` uses:

  1. The CLI binds a local HTTP server on 127.0.0.1, on any free port.
  2. It opens the browser at Zitadel's authorize endpoint with a PKCE challenge
     and ``redirect_uri=http://127.0.0.1:<port>/callback``.
  3. The user signs in (Zitadel login V2, GitHub or any other IdP).
  4. Zitadel redirects the browser to the local server with a one-time code.
  5. The CLI exchanges that code, plus the PKCE verifier, for a token.

No client secret is involved: the Zitadel app is public (NATIVE, auth method
NONE), and PKCE is what proves the token request comes from the process that
started the login. Zitadel matches loopback redirects on host and path but not
on port, so any free port works.

Why not the two earlier designs (kubecore-operator #1347):

  - Capturing oauth2-proxy's ``_lakefs_oauth2`` cookie on localhost can never
    work. The cookie is Secure+HttpOnly and oauth2-proxy strips it before it
    reaches anything the CLI could read. The browser only ever hands a
    localhost callback what the *authorization server* puts in the redirect,
    which here is the code.
  - Device flow: Zitadel serves the device page from its legacy V1 login UI,
    whose GitHub callback is not registered, so approval dies on GitHub. The
    authorize endpoint goes through login V2, which works.

The resulting token is per-user, short-lived, audience-scoped to the project
and revocable in Zitadel. oauth2-proxy accepts it as a bearer
(``--skip-jwt-bearer-tokens``) exactly as it does for the MeluXina HPC jobs.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from typing import Optional

import requests

CALLBACK_PATH = "/callback"

# How long to wait for the user to finish signing in. The clock starts when the
# browser opens, and the user still has to read the login page, type a password
# and clear 2FA, so this must budget a human, not a machine.
LOGIN_TIMEOUT = int(os.environ.get("KUBECORE_ML_LOGIN_TIMEOUT", "180"))


class LoginError(RuntimeError):
    """The browser login failed, was denied, or timed out."""


def discover_endpoints(issuer: str, timeout: int = 30) -> dict:
    """Read the authorize and token endpoints from OIDC discovery."""
    url = issuer.rstrip("/")
    if not url.endswith("/.well-known/openid-configuration"):
        url = f"{url}/.well-known/openid-configuration"
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        doc = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise LoginError(f"could not read OIDC discovery at {url}: {exc}") from exc

    authorize, token = doc.get("authorization_endpoint"), doc.get("token_endpoint")
    if not authorize or not token:
        raise LoginError(f"{url} does not advertise authorization and token endpoints")
    return {"authorization_endpoint": authorize, "token_endpoint": token}


def make_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, S256 code_challenge) per RFC 7636."""
    verifier = secrets.token_urlsafe(64)  # 86 chars, inside the 43..128 bound
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def scopes_for(audience_project_id: Optional[str]) -> str:
    scopes = ["openid", "profile", "offline_access"]
    if audience_project_id:
        # oauth2-proxy validates the bearer against --extra-jwt-issuers, which
        # names the Zitadel PROJECT id as the expected audience. Without this
        # scope the token is minted but lakeFS rejects it.
        scopes.append(f"urn:zitadel:iam:org:project:id:{audience_project_id}:aud")
    return " ".join(scopes)


def build_authorize_url(authorize_endpoint: str, client_id: str, redirect_uri: str,
                        challenge: str, state: str,
                        audience_project_id: Optional[str] = None) -> str:
    query = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes_for(audience_project_id),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    return f"{authorize_endpoint}?{query}"


def _make_handler(result: dict):
    """One-shot handler that records the redirect's query string."""

    class _Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_response(404)
                self.end_headers()
                return
            params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            result.setdefault("params", params)
            ok = "code" in params and "error" not in params
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            title = "Signed in." if ok else "Sign-in failed."
            body = ("You can close this tab and return to the terminal." if ok
                    else "Return to the terminal for details.")
            self.wfile.write(
                ("<!doctype html><meta charset=utf-8><title>kubecore-dataset</title>"
                 "<body style='font-family:system-ui,sans-serif;padding:3rem'>"
                 f"<h2>{title}</h2><p>{body}</p></body>").encode("utf-8"))

        def log_message(self, *args):  # keep the terminal clean
            pass

    return _Callback


def exchange_code(token_endpoint: str, client_id: str, code: str, redirect_uri: str,
                  verifier: str, timeout: int = 30) -> dict:
    """Swap the authorization code and PKCE verifier for tokens."""
    try:
        r = requests.post(token_endpoint, timeout=timeout, data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,  # must match the authorize request exactly
            "client_id": client_id,
            "code_verifier": verifier,
        })
        payload = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise LoginError(f"token request failed: {exc}") from exc
    if payload.get("error"):
        raise LoginError(f"token request rejected: {payload['error']} - "
                         f"{payload.get('error_description', '')}")
    if not payload.get("access_token"):
        raise LoginError("token response carried no access_token")
    return payload


def _wait_for_redirect(result: dict, timeout: int) -> None:
    tty = sys.stdout.isatty()
    deadline = time.time() + timeout
    try:
        while time.time() < deadline and "params" not in result:
            if tty:
                sys.stdout.write(f"\r\033[K⏳  Waiting for you to sign in… {int(deadline - time.time())}s")
                sys.stdout.flush()
            time.sleep(0.5)
    finally:
        if tty:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()


def login(issuer: str, client_id: str, audience_project_id: Optional[str] = None,
          timeout: int = LOGIN_TIMEOUT, open_browser: bool = True) -> dict:
    """Run the whole browser login and return Zitadel's token payload."""
    endpoints = discover_endpoints(issuer)
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(24)

    result: dict = {}
    # Port 0: the OS picks a free port. Zitadel accepts any loopback port.
    server = http.server.HTTPServer(("127.0.0.1", 0), _make_handler(result))
    redirect_uri = f"http://127.0.0.1:{server.server_address[1]}{CALLBACK_PATH}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2},
                              daemon=True)
    thread.start()
    try:
        url = build_authorize_url(endpoints["authorization_endpoint"], client_id,
                                  redirect_uri, challenge, state, audience_project_id)
        print("\n🔑  Opening your browser to sign in…")
        print(f"    {url}")
        print("    (open the link above yourself if the browser didn't start)\n")
        if open_browser:
            try:
                webbrowser.open(url)
            except webbrowser.Error:
                pass
        _wait_for_redirect(result, timeout)
    finally:
        server.shutdown()
        server.server_close()

    params = result.get("params")
    if params is None:
        raise LoginError("timed out waiting for the browser sign-in")
    if params.get("error"):
        raise LoginError(f"sign-in failed: {params['error']} - {params.get('error_description', '')}")
    # state binds this redirect to the request we sent; anything else is not ours.
    if params.get("state") != state:
        raise LoginError("sign-in returned an unexpected state; refusing the code")
    if not params.get("code"):
        raise LoginError("sign-in returned no authorization code")

    tokens = exchange_code(endpoints["token_endpoint"], client_id, params["code"],
                           redirect_uri, verifier)
    print("✓ Signed in.")
    return tokens
