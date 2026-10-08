"""Validate a local dataset against the Ultralytics-pose contract the pipeline
enforces, BEFORE uploading — so a run never fails deep in the pipeline on
"Dataset path not found or empty" or a structural error.

The rules here are a faithful local mirror of the pipeline's own checks in
``dataset_loading/app/services/dataset_loading.py`` (``_check_s3_structure``,
``_validate_data_yaml``, ``_spot_check_labels``). Keep them in sync: if the
pipeline tightens its contract, tighten here too, or the CLI will pass datasets
the pipeline later rejects.

A dataset directory must look like (at its root — this becomes the lakeFS ref
root, ``s3://<repo>/<branch>/``):

    data.yaml                 # path, train, val, kpt_shape, names
    images/train/*.{jpg,...}  # required split
    images/val/*.{jpg,...}    # required split
    images/test/*             # optional
    labels/train/*.txt        # 1:1 stem match with images/train
    labels/val/*.txt
    labels/test/*             # optional
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Optional

import yaml

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
REQUIRED_SPLITS = ("train", "val")
OPTIONAL_SPLITS = ("test",)
ALL_SPLITS = REQUIRED_SPLITS + OPTIONAL_SPLITS
REQUIRED_YAML_KEYS = {"path", "train", "val", "kpt_shape", "names"}

# How many label files per split to spot-check for token/format correctness.
_SPOT_CHECK_FILES = 20


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def report(self) -> str:
        lines = []
        if self.ok:
            lines.append("✓ Dataset is valid (Ultralytics-pose).")
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


def _expected_pose_tokens(kpt_shape: list[int]) -> int:
    # Ultralytics pose row: class(1) + bbox(4) + N_kpts * kpt_dim
    return 1 + 4 + kpt_shape[0] * kpt_shape[1]


def _validate_data_yaml(root: pathlib.Path, errors: list[str]) -> Optional[list[int]]:
    """Mirror of dataset_loading._validate_data_yaml. Returns kpt_shape or None."""
    yaml_path = root / "data.yaml"
    if not yaml_path.exists():
        errors.append(
            "data.yaml not found at the dataset root. A valid Ultralytics YOLO "
            "dataset must include data.yaml."
        )
        return None
    try:
        content = yaml.safe_load(yaml_path.read_text()) or {}
    except yaml.YAMLError as exc:
        errors.append(f"data.yaml is not valid YAML: {exc}")
        return None

    missing = REQUIRED_YAML_KEYS - set(content.keys())
    if missing:
        errors.append(f"data.yaml is missing required keys: {sorted(missing)}")

    names = content.get("names")
    if names is not None:
        if not isinstance(names, dict):
            errors.append(
                f"data.yaml 'names' must be a dict mapping int -> str, "
                f"got {type(names).__name__}"
            )
        else:
            for k, v in names.items():
                if not isinstance(k, int) or not isinstance(v, str):
                    errors.append(
                        f"data.yaml 'names' entries must be int: str, got "
                        f"{type(k).__name__}: {type(v).__name__} for {k!r}: {v!r}"
                    )
                    break

    kpt_shape = content.get("kpt_shape")
    valid_kpt = (
        isinstance(kpt_shape, list)
        and len(kpt_shape) == 2
        and isinstance(kpt_shape[0], int)
        and kpt_shape[0] >= 1
        and kpt_shape[1] in (2, 3)
    )
    if kpt_shape is not None and not valid_kpt:
        errors.append(
            f"data.yaml 'kpt_shape' must be [N, 2] or [N, 3] with N >= 1, "
            f"got {kpt_shape!r}"
        )

    if isinstance(names, dict) and "nc" in content and content["nc"] != len(names):
        errors.append(
            f"data.yaml 'nc' ({content['nc']}) does not match len(names) ({len(names)})"
        )

    return kpt_shape if valid_kpt else None


def _split_files(root: pathlib.Path, kind: str, split: str, suffixes) -> dict[str, pathlib.Path]:
    """Return {stem: path} for images/labels of a split, filtered by suffix."""
    d = root / kind / split
    out: dict[str, pathlib.Path] = {}
    if not d.is_dir():
        return out
    for p in d.rglob("*"):
        if p.is_file() and p.suffix.lower() in suffixes:
            out[p.stem] = p
    return out


def _spot_check_labels(label_paths: list[pathlib.Path], expected_tokens: int,
                       num_classes: int, kpt_dim: int, errors: list[str]) -> None:
    """Mirror of dataset_loading._spot_check_labels on the first N files."""
    for label_path in label_paths[:_SPOT_CHECK_FILES]:
        try:
            lines = label_path.read_text().splitlines()
        except OSError as exc:
            errors.append(f"cannot read label {label_path}: {exc}")
            continue
        for lineno, raw in enumerate(lines, start=1):
            line = raw.strip()
            if not line:
                continue
            tokens = line.split()
            if len(tokens) != expected_tokens:
                errors.append(
                    f"{label_path.name} line {lineno}: expected {expected_tokens} "
                    f"tokens for this kpt_shape, got {len(tokens)}"
                )
                break
            try:
                values = [float(t) for t in tokens]
            except ValueError:
                errors.append(f"{label_path.name} line {lineno}: non-numeric token")
                break
            cls_id = values[0]
            if cls_id != int(cls_id) or cls_id < 0 or int(cls_id) >= num_classes:
                errors.append(
                    f"{label_path.name} line {lineno}: class ID {cls_id} out of "
                    f"range [0, {num_classes})"
                )
                break
            for name, val in zip(("cx", "cy", "w", "h"), values[1:5]):
                if not 0.0 <= val <= 1.0:
                    errors.append(
                        f"{label_path.name} line {lineno}: bbox {name}={val} outside [0,1]"
                    )
                    break


def validate_dataset(dataset_dir: str | pathlib.Path) -> ValidationResult:
    """Validate a local dataset directory. Never raises — returns a result."""
    root = pathlib.Path(dataset_dir)
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict = {}

    if not root.is_dir():
        return ValidationResult(False, [f"{root} is not a directory"])

    # 1) data.yaml
    kpt_shape = _validate_data_yaml(root, errors)

    # names → num_classes (best effort for label checks)
    num_classes = 1
    data_yaml = root / "data.yaml"
    if data_yaml.exists():
        try:
            content = yaml.safe_load(data_yaml.read_text()) or {}
            if isinstance(content.get("names"), dict):
                num_classes = len(content["names"]) or 1
        except yaml.YAMLError:
            pass

    # 2) required splits present & non-empty; stem matching per split
    total_pairs = 0
    for split in ALL_SPLITS:
        images = _split_files(root, "images", split, SUPPORTED_IMAGE_EXTENSIONS)
        labels = _split_files(root, "labels", split, {".txt"})
        stats[f"images/{split}"] = len(images)
        stats[f"labels/{split}"] = len(labels)

        if split in REQUIRED_SPLITS:
            if not images:
                errors.append(f"images/{split}/ has no files — 'train' and 'val' are required")
            if not labels:
                errors.append(f"labels/{split}/ has no files — 'train' and 'val' are required")
        elif not images and not labels:
            continue  # optional split simply absent

        # stem matching: every image needs a same-stem label in the same split
        missing = [s for s in images if s not in labels]
        if missing:
            sample = ", ".join(f"{split}/{s}" for s in missing[:5])
            extra = len(missing) - min(5, len(missing))
            if extra:
                sample += f" ... and {extra} more"
            errors.append(
                f"{len(missing)} image(s) in '{split}' have no matching label: {sample}"
            )
        # warn on orphan labels (label with no image) — not fatal, but noise
        orphan = [s for s in labels if s not in images]
        if orphan:
            warnings.append(
                f"{len(orphan)} label(s) in '{split}' have no matching image "
                f"(e.g. {orphan[0]}) — they will train nothing"
            )
        total_pairs += sum(1 for s in images if s in labels)

        # 3) spot-check label token format when kpt_shape is known
        if kpt_shape and labels:
            _spot_check_labels(
                sorted(labels.values()),
                _expected_pose_tokens(kpt_shape),
                num_classes,
                kpt_shape[1],
                errors,
            )

    stats["image-label pairs"] = total_pairs
    if kpt_shape:
        stats["kpt_shape"] = kpt_shape

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings, stats=stats)
