"""Per-app config discovery. Nothing about an instance is hardcoded.

The platform writes ``.kubecore/dataset-config.yaml`` into every app repo
(lakefsUrl, repo, oidcIssuer, oidcClientId, oidcProjectId, ...). Precedence for
every value: explicit argument > environment variable > this file (searched
upward from the start dir and the CWD).
"""
from __future__ import annotations

import os
import pathlib
from functools import lru_cache
from typing import Optional

import yaml

from .errors import ConfigError

CONFIG_RELPATH = pathlib.Path(".kubecore") / "dataset-config.yaml"
ENDPOINT_ENVS = ("LAKEFS_ENDPOINT", "LAKEFS_URL")  # LAKEFS_ENDPOINT is what steps/HPC get


def _find_config(start: Optional[pathlib.Path]) -> Optional[pathlib.Path]:
    """Walk up from ``start`` and the CWD looking for the config file."""
    roots = ([pathlib.Path(start).resolve()] if start else []) + [pathlib.Path.cwd().resolve()]
    seen: set = set()
    for root in roots:
        cur = root if root.is_dir() else root.parent
        while cur not in seen:
            seen.add(cur)
            if (cur / CONFIG_RELPATH).is_file():
                return cur / CONFIG_RELPATH
            if cur.parent == cur:
                break
            cur = cur.parent
    return None


@lru_cache(maxsize=8)
def load_config(start: Optional[str] = None) -> dict:
    """Load the per-app config, or ``{}`` when there is none or it is unreadable."""
    override = os.environ.get("KUBECORE_DATASET_CONFIG")
    path = pathlib.Path(override) if override else _find_config(pathlib.Path(start) if start else None)
    if not path or not path.is_file():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return {}


def config_value(key: str, start: Optional[str] = None) -> Optional[str]:
    """One value from the per-app config as a string, or None."""
    value = load_config(start).get(key)
    return str(value) if value is not None else None


def resolve_endpoint(explicit: Optional[str] = None, start: Optional[str] = None) -> str:
    """The lakeFS base URL (no trailing slash): argument > env > per-app config."""
    url = explicit or next((os.environ[e] for e in ENDPOINT_ENVS if os.environ.get(e)), None) \
        or config_value("lakefsUrl", start)
    if not url:
        raise ConfigError(
            "cannot determine the lakeFS URL. Run inside your app clone (it carries "
            ".kubecore/dataset-config.yaml), pass --url, or set LAKEFS_ENDPOINT.")
    return url.rstrip("/")


def oidc_settings(start: Optional[str] = None) -> tuple:
    """(issuer, client_id, audience_project_id) for the browser login; any may be None."""
    return (os.environ.get("KUBECORE_ML_OIDC_ISSUER") or config_value("oidcIssuer", start),
            os.environ.get("KUBECORE_ML_OIDC_CLIENT_ID") or config_value("oidcClientId", start),
            os.environ.get("KUBECORE_ML_OIDC_PROJECT_ID") or config_value("oidcProjectId", start))
