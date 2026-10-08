"""Per-app config discovery — so the CLI carries NO hardcoded instance values.

Every ML app is different (its own lakeFS instance, repo, namespace). The CLI
must never assume a specific URL. Instead the platform writes a per-app config
file into the app repo at render time, and the CLI discovers it:

    .kubecore/dataset-config.yaml     (rendered by render-wft / the reconciler)
        lakefsUrl:  https://lakefs-<project>.<baseDns>   # EXTERNAL ingress
        repo:       <project>
        namespace:  ml-<project>
        probeCron:  <app>-dataset-catalog-probe

Resolution precedence for every value: explicit CLI flag > environment variable
> this config file (searched upward from the dataset dir and CWD) > None. So a
developer just runs `kubecore-dataset upload ./data <branch>` inside their app
clone and everything is filled in — nothing hardcoded, works for any instance.
"""
from __future__ import annotations

import os
import pathlib
from functools import lru_cache
from typing import Optional

import yaml

CONFIG_RELPATH = pathlib.Path(".kubecore") / "dataset-config.yaml"


def _find_config(start: Optional[pathlib.Path] = None) -> Optional[pathlib.Path]:
    """Walk up from start (and CWD) looking for .kubecore/dataset-config.yaml."""
    roots = []
    if start:
        roots.append(pathlib.Path(start).resolve())
    roots.append(pathlib.Path.cwd().resolve())
    seen = set()
    for root in roots:
        cur = root if root.is_dir() else root.parent
        while cur and cur not in seen:
            seen.add(cur)
            candidate = cur / CONFIG_RELPATH
            if candidate.is_file():
                return candidate
            if cur.parent == cur:
                break
            cur = cur.parent
    return None


@lru_cache(maxsize=8)
def load_config(start: Optional[str] = None) -> dict:
    """Load the per-app dataset config, or {} if none is found."""
    override = os.environ.get("KUBECORE_DATASET_CONFIG")
    path = pathlib.Path(override) if override else _find_config(
        pathlib.Path(start) if start else None
    )
    if not path or not path.is_file():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return {}


def config_value(key: str, start: Optional[str] = None) -> Optional[str]:
    v = load_config(start).get(key)
    return str(v) if v is not None else None
