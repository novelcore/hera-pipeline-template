"""Check a local dataset folder before it is uploaded.

This template does not fix a data format: your steps decide what they read. So
the only checks here are the ones that hold for any dataset: the folder exists,
it contains files, and nothing in it would upload as junk.

To catch format mistakes on the laptop instead of in a failed run, add your own
checks to ``check_format`` below (e.g. "data.yaml is present", "every image has
a label"). Anything appended to ``errors`` stops the upload; ``warnings`` are
printed and the upload continues.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

# Editor and OS droppings that should never end up in a versioned dataset.
_JUNK = {".DS_Store", "Thumbs.db", "desktop.ini"}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def report(self) -> str:
        lines = []
        if self.ok:
            lines.append("✓ Dataset folder looks fine.")
        else:
            lines.append(f"✗ Dataset is INVALID ({len(self.errors)} error(s)):")
        for e in self.errors:
            lines.append(f"    ✗ {e}")
        for w in self.warnings:
            lines.append(f"    ! {w}")
        if self.stats:
            lines.append("  Summary:")
            for k, v in self.stats.items():
                lines.append(f"    {k}: {v}")
        return "\n".join(lines)


def check_format(root: pathlib.Path, files: list[pathlib.Path],
                 errors: list[str], warnings: list[str]) -> None:
    """Your data format's checks go here. Empty by default: any files pass."""


def validate_dataset(dataset_dir: str | pathlib.Path) -> ValidationResult:
    root = pathlib.Path(dataset_dir)
    errors: list[str] = []
    warnings: list[str] = []

    if not root.is_dir():
        return ValidationResult(ok=False, errors=[f"{root} is not a folder"])

    files = [p for p in root.rglob("*") if p.is_file()]
    junk = [p for p in files if p.name in _JUNK]
    files = [p for p in files if p.name not in _JUNK]
    if not files:
        errors.append(f"{root} has no files to upload")
    if junk:
        warnings.append(f"{len(junk)} system file(s) such as {junk[0].name} will be "
                        "uploaded too; delete them if you don't want them versioned")

    check_format(root, files, errors, warnings)

    stats = {"files": len(files) + len(junk),
             "total size": f"{sum(p.stat().st_size for p in files) / 1e6:.1f} MB"}
    return ValidationResult(ok=not errors, errors=errors, warnings=warnings, stats=stats)
