"""Dataset formats (``ultralytics``, and ``raw`` for any repository): each is a creator (build, validate, publish) plus a consumer (materialize).

``get_format("ultralytics")`` returns the pair. ``yolo`` is accepted as an alias
(kaos-lake is renaming its template ``yolo`` -> ``ultralytics``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..errors import DatasetError


MAX_SHOWN = 30


@dataclass
class ValidationReport:
    """Every problem found in a local dataset (aggregated, never first-error-only)."""
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def format(self) -> str:
        shown = self.errors[:MAX_SHOWN]
        lines = [f"  - {e}" for e in shown]
        if len(self.errors) > len(shown):
            lines.append(f"  ... and {len(self.errors) - len(shown)} more")
        return "\n".join(lines) if lines else "dataset is valid"


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


from . import raw, ultralytics  # noqa: E402,F401  (register themselves)
