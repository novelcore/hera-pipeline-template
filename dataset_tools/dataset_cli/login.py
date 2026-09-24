"""lakeFS login for the dataset CLI.

lakeFS sits behind oauth2-proxy (Zitadel) and an nginx sidecar that injects the
shared lakeFS admin Basic-auth header server-side; lakeFS OSS runs in
basic_auth mode with no per-user identity. oauth2-proxy is the gate, and it
accepts two credentials:

  1. A Zitadel bearer token — the normal path. ``oidc_login`` gets one through
     a browser login (authorization code + PKCE on a loopback redirect), and
     oauth2-proxy verifies it against Zitadel's JWKS
     (``--skip-jwt-bearer-tokens``). Nothing is pasted.
  2. The ``_lakefs_oauth2`` session cookie — the manual fallback, only offered
     when the app repo carries no OIDC settings yet (the project's CLI app is
     not provisioned). The user copies it out of the browser.

The credential is cached (0600) at ~/.config/kubecore-ml/lakefs-session.json
so ``validate``/``sync`` reuse it until it expires.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import webbrowser
from dataclasses import dataclass
from typing import Optional

from . import oidc_login
from .appconfig import config_value
from .lakefs_client import LakeFSClient


@dataclass(frozen=True)
class Credential:
    """What the CLI carries to lakeFS.

    ``token`` is a per-user Zitadel bearer from the browser login — the normal path.
    ``cookie`` is the legacy oauth2-proxy session, kept only so a cached
    pre-upgrade session and the manual paste escape hatch keep working.
    """
    token: Optional[str] = None
    cookie: Optional[str] = None

    @property
    def kind(self) -> str:
        return "bearer" if self.token else "cookie"

SESSION_PATH = pathlib.Path(
    os.environ.get("KUBECORE_ML_HOME", pathlib.Path.home() / ".config" / "kubecore-ml")
) / "lakefs-session.json"


# ----------------------------------------------------------------------
# session cache
# ----------------------------------------------------------------------
def save_session(base_url: str, cookie: Optional[str] = None,
                 token: Optional[str] = None) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"base_url": base_url.rstrip("/")}
    if token:
        payload["token"] = token
    if cookie:
        payload["cookie"] = cookie
    SESSION_PATH.write_text(json.dumps(payload))
    os.chmod(SESSION_PATH, 0o600)


def load_session(base_url: Optional[str] = None) -> Optional[Credential]:
    """Return a cached, still-valid credential for base_url, else None.

    Reads both the current {"token": ...} shape and the legacy {"cookie": ...}
    one, so an existing session file keeps working after an upgrade.
    """
    if not SESSION_PATH.exists():
        return None
    try:
        data = json.loads(SESSION_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if base_url and data.get("base_url") != base_url.rstrip("/"):
        return None

    token, cookie = data.get("token"), data.get("cookie")
    if not token and not cookie:
        return None
    cred = Credential(token=token, cookie=cookie)
    # verify it still authenticates (tokens expire; cookies are 4h)
    client = LakeFSClient(data["base_url"], cookie=cookie, token=token)
    return cred if client.check_auth() else None


# ----------------------------------------------------------------------
# guided paste fallback
# ----------------------------------------------------------------------
def guided_paste_login(base_url: str) -> Optional[str]:
    base_url = base_url.rstrip("/")
    print("\n🔑  Log in here (opens in your browser):")
    print(f"    {base_url}/\n")
    webbrowser.open(f"{base_url}/")
    print("After you're logged in, copy the `_lakefs_oauth2` cookie value")
    print("(DevTools → Application/Storage → Cookies) and paste it below,")
    print("then press Enter.\n")
    # Read via sys.stdin, NOT input(): on macOS, Python's input() uses libedit,
    # which breaks on pastes longer than the terminal width — the line wraps and
    # Enter stops submitting (a session cookie/JWT is hundreds of chars). Reading
    # the raw line has no line-editor, so long pastes + Enter work everywhere.
    sys.stdout.write("_lakefs_oauth2 = ")
    sys.stdout.flush()
    try:
        line = sys.stdin.readline()
    except (EOFError, KeyboardInterrupt):
        return None
    if not line:  # EOF (Ctrl-D)
        return None
    cookie = line.strip()
    return cookie or None


# ----------------------------------------------------------------------
# entry
# ----------------------------------------------------------------------
def oidc_settings(start: Optional[str] = None) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Resolve (issuer, client_id, audience_project_id) for the browser login.

    Precedence: environment > .kubecore/dataset-config.yaml. The operator
    publishes these per project (KubeProject.status.mlStack.datasetCLIOIDC,
    kubecore-operator #1347) and the render step writes them into the app repo,
    so nothing is hardcoded and every project gets its own app.
    """
    issuer = os.environ.get("KUBECORE_ML_OIDC_ISSUER") or config_value("oidcIssuer", start)
    client_id = os.environ.get("KUBECORE_ML_OIDC_CLIENT_ID") or config_value("oidcClientId", start)
    audience = (os.environ.get("KUBECORE_ML_OIDC_PROJECT_ID")
                or config_value("oidcProjectId", start))
    return issuer, client_id, audience


def browser_login() -> Optional[Credential]:
    """Log in through the browser. Returns None if it is not configured or fails."""
    issuer, client_id, audience = oidc_settings()
    if not issuer or not client_id:
        return None
    try:
        tokens = oidc_login.login(issuer, client_id, audience_project_id=audience)
    except oidc_login.LoginError as exc:
        print(f"\nBrowser sign-in failed: {exc}")
        return None
    token = tokens.get("access_token")
    return Credential(token=token) if token else None


def login(base_url: str, force: bool = False, prefer_paste: bool = False) -> Credential:
    """Return a valid credential for base_url; log in via browser if needed.

    Order: session cache -> browser login (PKCE) -> guided paste (opt-in).

    The browser login is the normal path; the paste fallback survives only for
    projects whose CLI OIDC app is not provisioned yet.
    """
    base_url = base_url.rstrip("/")

    if not force:
        cached = load_session(base_url)
        if cached:
            print(f"✓ Using cached lakeFS session ({cached.kind}).")
            return cached

    cred: Optional[Credential] = None
    if not prefer_paste:
        cred = browser_login()
        if cred is None:
            issuer, client_id, _ = oidc_settings()
            if not issuer or not client_id:
                print("\nBrowser sign-in is not configured for this app "
                      "(no oidcIssuer/oidcClientId in .kubecore/dataset-config.yaml).")
            print("Falling back to the manual cookie paste.")
            sys.stdout.write("Continue with a manual paste? [y/N] ")
            sys.stdout.flush()
            try:
                answer = sys.stdin.readline().strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if answer not in ("y", "yes"):
                sys.exit("Aborted — not signed in.")

    if cred is None:
        cookie = guided_paste_login(base_url)
        if not cookie:
            sys.exit("ERROR: no lakeFS credential was captured. Aborting.")
        cred = Credential(cookie=cookie)

    # verify before caching
    client = LakeFSClient(base_url, cookie=cred.cookie, token=cred.token)
    if not client.check_auth():
        sys.exit(
            f"ERROR: the captured {cred.kind} did not authenticate to lakeFS "
            "(invalid or expired). Try again."
        )
    save_session(base_url, cookie=cred.cookie, token=cred.token)
    print("✓ Logged in — session cached.")
    return cred
