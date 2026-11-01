"""The one credential chain for lakeFS. No secret is ever stored in the package.

Order (first hit wins):
  1. LAKEFS_ACCESS_KEY + LAKEFS_SECRET_KEY   an app's key pair (pods, CI) -> Basic auth
  2. LAKEFS_BEARER_TOKEN                     a bearer token (MeluXina jobs)
  3. the cached browser-login session       a person's Zitadel token (laptop)

The session cache is ~/.config/kubecore-ml/lakefs-session.json (0600), the file
the earlier ``kubecore-dataset`` CLI wrote, so an existing login keeps working.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import Optional

from . import oidc
from .config import oidc_settings
from .errors import AuthError


@dataclass(frozen=True)
class Credential:
    """How to authenticate to lakeFS: a bearer ``token`` or an access-key pair."""
    token: Optional[str] = None
    access_key: Optional[str] = None
    secret_key: Optional[str] = None

    @property
    def kind(self) -> str:
        return "bearer" if self.token else "access key"


def session_path() -> pathlib.Path:
    """Where the login session is cached (re-evaluated so tests/env can redirect it)."""
    home = os.environ.get("KUBECORE_ML_HOME") or pathlib.Path.home() / ".config" / "kubecore-ml"
    return pathlib.Path(home) / "lakefs-session.json"


def from_env() -> Optional[Credential]:
    """Credential from the environment (chain steps 1 and 2), or None."""
    key, secret = os.environ.get("LAKEFS_ACCESS_KEY"), os.environ.get("LAKEFS_SECRET_KEY")
    if key and secret:
        return Credential(access_key=key, secret_key=secret)
    token = os.environ.get("LAKEFS_BEARER_TOKEN")
    return Credential(token=token) if token else None


def save_session(base_url: str, token: str) -> None:
    """Cache a login token for ``base_url`` (file mode 0600)."""
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"base_url": base_url.rstrip("/"), "token": token}))
    os.chmod(path, 0o600)


def load_session(base_url: str) -> Optional[Credential]:
    """The cached login token for ``base_url`` (chain step 3), or None."""
    try:
        data = json.loads(session_path().read_text())
    except (OSError, ValueError):
        return None
    if data.get("base_url") != base_url.rstrip("/") or not data.get("token"):
        return None
    return Credential(token=data["token"])


def resolve(base_url: str) -> Credential:
    """Walk the chain; raise AuthError telling the user what to do when it is empty."""
    cred = from_env() or load_session(base_url)
    if cred is None:
        raise AuthError(
            "not signed in. Run `kubecore login`, or set LAKEFS_ACCESS_KEY/LAKEFS_SECRET_KEY "
            "(or LAKEFS_BEARER_TOKEN) in the environment.")
    return cred


def browser_login(base_url: str, start: Optional[str] = None) -> Credential:
    """Sign in through the browser (Zitadel PKCE), cache the token and return it."""
    issuer, client_id, audience = oidc_settings(start)
    if not issuer or not client_id:
        raise AuthError(
            "browser sign-in is not configured for this app (no oidcIssuer/oidcClientId in "
            ".kubecore/dataset-config.yaml). Run inside your app clone, or use an access key.")
    try:
        tokens = oidc.login(issuer, client_id, audience_project_id=audience)
    except oidc.LoginError as exc:
        raise AuthError(f"browser sign-in failed: {exc}") from exc
    token = tokens["access_token"]
    save_session(base_url, token)
    print("Logged in; session cached.", file=sys.stderr)
    return Credential(token=token)
