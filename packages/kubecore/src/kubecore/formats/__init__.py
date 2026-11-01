"""Dataset formats: each is a creator (build, validate, publish) plus a consumer (materialize).

``get_format("ultralytics")`` returns the pair. ``yolo`` is accepted as an alias
(kaos-lake is renaming its template ``yolo`` -> ``ultralytics``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import DatasetError


@dataclass(frozen=True)
class Format:
    """A named creator + consumer pair."""
    name: str
    creator: Any   # skeleton(**opts)->{path: bytes}, validate(dir), publish(dir, repo, message, ...)
    consumer: Any  # materialize(ref, dest, client) -> Path


_REGISTRY: dict = {}
_ALIASES = {"yolo": "ultralytics"}


def register(fmt: Format) -> None:
    """Add a format to the registry (last registration of a name wins)."""
    _REGISTRY[fmt.name] = fmt


def get_format(name: str) -> Format:
    """The format called ``name`` (aliases resolved); DatasetError listing the known ones otherwise."""
    key = _ALIASES.get(name, name)
    if key not in _REGISTRY:
        raise DatasetError(f"unknown dataset format {name!r}. Known: {', '.join(sorted(_REGISTRY))}.")
    return _REGISTRY[key]


def format_names() -> list:
    return sorted(_REGISTRY)


from . import ultralytics  # noqa: E402,F401  (registers itself)
