"""The ``ultralytics`` dataset format: the YOLO layout Ultralytics reads.

    data.yaml                path / train / val / test / nc / names
    images/{train,val,test}/ the images
    labels/{train,val,test}/ one <image-stem>.txt per image: "<class-id> <x> <y> <w> <h>" lines, coords in [0,1]

``UltralyticsCreator`` builds, validates and publishes; ``UltralyticsConsumer``
materializes a pinned version for training. Registered as ``ultralytics``.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Optional, Sequence

import yaml

from .. import datasets
from ..errors import DatasetError, ValidationFailed
from ..lakefs import LakeFS
from ..transfer import download_prefixes
from . import Format, register

NAME = "ultralytics"
SPLITS = ("train", "val", "test")
REQUIRED_SPLITS = ("train", "val")  # Ultralytics trains on train and validates on val; test is optional
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
DOWNLOAD_PREFIXES = ("data.yaml", "images/", "labels/")  # everything training reads, nothing else
MARKER = ".kubecore-dataset.json"
STAGED_ENV, CACHE_ENV = "KUBECORE_STAGED_DIR", "KUBECORE_CACHE_DIR"
STAGED_COMMIT_FILES = (".kaos-commit", ".kaos-ready")  # MeluXina stager markers that may hold the commit
MAX_SHOWN = 30


# --------------------------------------------------------------------- validation
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


def _load_data_yaml(root: pathlib.Path, errors: list) -> Optional[dict]:
    path = root / "data.yaml"
    if not path.is_file():
        errors.append("data.yaml is missing")
        return None
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        errors.append(f"data.yaml is not valid YAML: {exc}")
        return None
    if not isinstance(data, dict):
        errors.append("data.yaml must be a mapping (path, train, val, nc, names)")
        return None
    return data


def _names_from_mapping(names: dict, errors: list) -> list:
    """Class names ordered by integer id; ids must be integers and exactly 0..n-1."""
    if any(isinstance(k, bool) or not isinstance(k, int) for k in names):
        errors.append("data.yaml: names keys must be integer class ids (0, 1, 2, ...)")
        return list(names.values())
    if sorted(names) != list(range(len(names))):
        errors.append(f"data.yaml: names ids must be exactly 0..{len(names) - 1}, got {sorted(names)}")
    return [names[k] for k in sorted(names)]  # numeric order: 0,1,2,...,10 (never string order)


def _check_classes(data: dict, errors: list) -> Optional[int]:
    """Check nc/names; returns nc when usable for label checks."""
    nc, names = data.get("nc"), data.get("names")
    if isinstance(nc, bool) or not isinstance(nc, int) or nc < 1:
        errors.append(f"data.yaml: nc must be a positive integer (got {nc!r})")
        nc = None
    if isinstance(names, dict):
        names = _names_from_mapping(names, errors)
    if not isinstance(names, list) or not names:
        errors.append("data.yaml: names must be a non-empty list (or an id -> name mapping)")
    elif nc is not None and nc != len(names):
        errors.append(f"data.yaml: nc is {nc} but names has {len(names)} entries")
    return nc


def _split_dirs(data: dict, split: str, errors: list) -> Optional[tuple]:
    """(images dir, labels dir) relative paths for a split, or None when absent/invalid."""
    entry = data.get(split)
    if entry is None:
        if split in REQUIRED_SPLITS:
            errors.append(f"data.yaml: {split} is missing")
        return None
    entry = str(entry).strip("/")
    if not entry.startswith("images/"):
        errors.append(f"data.yaml: {split} must point below images/ (got {entry!r})")
        return None
    return entry, "labels/" + entry[len("images/"):]


def _check_label_file(label: pathlib.Path, rel: str, nc: Optional[int], errors: list) -> None:
    for n, line in enumerate(label.read_text().splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5:
            errors.append(f"{rel}:{n}: expected '<class-id> <x> <y> <w> <h>', got {len(parts)} values")
            continue
        try:
            cid, coords = int(parts[0]), [float(p) for p in parts[1:]]
        except ValueError:
            errors.append(f"{rel}:{n}: class id must be an integer and x y w h numbers: {line.strip()!r}")
            continue
        if cid < 0 or (nc is not None and cid >= nc):
            errors.append(f"{rel}:{n}: class id {cid} is outside 0..{(nc or 1) - 1}")
        if any(not 0.0 <= c <= 1.0 for c in coords):
            errors.append(f"{rel}:{n}: coordinates must be within [0,1]: {line.strip()!r}")


def _check_split(root: pathlib.Path, split: str, dirs: tuple, nc: Optional[int], errors: list) -> None:
    img_dir, lbl_dir = root / dirs[0], root / dirs[1]
    images = sorted(p for p in img_dir.rglob("*")
                    if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith("."))
    if not images and split in REQUIRED_SPLITS:
        errors.append(f"{dirs[0]}/ has no images")
    for img in images:
        label = lbl_dir / img.relative_to(img_dir).with_suffix(".txt")
        rel = label.relative_to(root).as_posix()
        if not label.is_file():
            errors.append(f"{img.relative_to(root).as_posix()} has no label file {rel}")
        else:
            _check_label_file(label, rel, nc, errors)


def validate(local_dir) -> ValidationReport:
    """Check a local dataset directory against the format; collects all problems."""
    root, errors = pathlib.Path(local_dir), []
    if not root.is_dir():
        return ValidationReport([f"{root} is not a directory"])
    data = _load_data_yaml(root, errors)
    if data is not None:
        nc = _check_classes(data, errors)
        for split in SPLITS:
            dirs = _split_dirs(data, split, errors)
            if dirs:
                _check_split(root, split, dirs, nc, errors)
    return ValidationReport(errors)


# --------------------------------------------------------------------- creator
README = """# {title}

{description}

Format: `ultralytics` (the YOLO layout Ultralytics reads).

- `data.yaml`: `path`, `train`, `val`, `test`, `nc` (class count) and `names`.
- `images/{{train,val,test}}/`: the images.
- `labels/{{train,val,test}}/`: one `<image-name>.txt` per image, one line per object:
  `<class-id> <x-center> <y-center> <width> <height>`, coordinates relative to the image (0 to 1).

Check a local copy with `kubecore dataset validate <dir>`; send changes with `kubecore dataset push`.
"""


DATA_YAML = """# YOLO dataset (Ultralytics). Paths are relative to the dataset's root.
path: .
train: images/train
val: images/val
test: images/test
nc: {nc}
names:
{names}
"""


class UltralyticsCreator:
    """Builds, validates and publishes ultralytics datasets."""

    name = NAME

    def skeleton(self, classes: Sequence[str], description: str = "", title: str = "Dataset") -> dict:
        """Files of a new, empty dataset: ``{repo path: bytes}`` (same layout as kaos-lake's template)."""
        names = [str(c).strip() for c in classes if str(c).strip()]
        if not names:
            raise DatasetError("an ultralytics dataset needs at least one class name (--classes a,b,c).")
        quoted = "\n".join(f"  {i}: {json.dumps(n)}" for i, n in enumerate(names))
        data_yaml = DATA_YAML.format(nc=len(names), names=quoted)
        files = {"data.yaml": data_yaml.encode(),
                 "README.md": README.format(title=title, description=description).encode()}
        for kind in ("images", "labels"):
            for split in SPLITS:
                files[f"{kind}/{split}/.keep"] = b""  # lakeFS has no empty directories
        return files

    def validate(self, local_dir) -> ValidationReport:
        return validate(local_dir)

    def publish(self, local_dir, repo: str, message: str, via_pull_request: bool = True,
                description: str = "", validate_first: bool = True,
                client: Optional[LakeFS] = None) -> datasets.PublishResult:
        """Validate, then upload ``local_dir`` to ``repo`` through a draft branch and a pull request.

        Creates ``repo`` first when missing (labels kaos.kind=dataset, kaos.template=ultralytics).
        Raises ValidationFailed with every problem when the dataset is invalid.
        """
        if validate_first:
            report = validate(local_dir)
            if not report.ok:
                raise ValidationFailed(report.errors)
        labels = {datasets.LABEL_KIND: "dataset", datasets.LABEL_TEMPLATE: NAME}
        if description:
            labels[datasets.LABEL_DESCRIPTION] = description
        return datasets.publish_tree(local_dir, repo, message, via_pull_request, labels, client)


# --------------------------------------------------------------------- consumer
def cache_root() -> pathlib.Path:
    """Default home of materialized datasets, keyed <repo>/<commit>."""
    return pathlib.Path(os.environ.get(CACHE_ENV) or pathlib.Path.home() / ".cache" / "kubecore" / "datasets")


def _marker_matches(directory: pathlib.Path, repo: str, commit: str) -> bool:
    try:
        m = json.loads((directory / MARKER).read_text())
    except (OSError, ValueError):
        return False
    return m.get("repo") == repo and m.get("commit") == commit and (directory / "data.yaml").is_file()


def _staged_dir(commit: str) -> Optional[pathlib.Path]:
    """The staged copy (KUBECORE_STAGED_DIR) when it holds ``commit``, else None."""
    raw = os.environ.get(STAGED_ENV)
    if not raw:
        return None
    staged = pathlib.Path(raw)
    if not (staged / "data.yaml").is_file():
        return None
    holders = [staged.name] + [
        (staged / f).read_text() for f in STAGED_COMMIT_FILES if (staged / f).is_file()]
    return staged if any(commit in h for h in holders) else None


def _write_data_yaml(source: pathlib.Path, out: pathlib.Path, dataset_path: pathlib.Path) -> pathlib.Path:
    """Copy ``source`` data.yaml to ``out`` with ``path:`` pointing at ``dataset_path``."""
    data = yaml.safe_load(source.read_text()) or {}
    data["path"] = str(dataset_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, sort_keys=False))
    return out


class UltralyticsConsumer:
    """Makes a pinned dataset version trainable locally."""

    name = NAME

    def materialize(self, ref: datasets.DatasetRef, dest=None, client: Optional[LakeFS] = None) -> pathlib.Path:
        """Local ``data.yaml`` Ultralytics can train on for ``ref``.

        Only data.yaml, images/ and labels/ are downloaded, at the pinned commit. Data lives in
        ``dest`` (default ``<cache>/<repo>/<commit>``); a second call for the same commit is free.
        A staged copy (KUBECORE_STAGED_DIR holding the commit) is used in place, nothing downloaded.
        """
        commit = datasets.resolve(ref, client)
        target = pathlib.Path(dest) if dest else cache_root() / ref.repo / commit
        staged = _staged_dir(commit)
        if staged:
            return _write_data_yaml(staged / "data.yaml", target / "data.yaml", staged)
        if _marker_matches(target, ref.repo, commit):
            return target / "data.yaml"
        self._download(ref, commit, target, client)
        return target / "data.yaml"

    def _download(self, ref, commit: str, target: pathlib.Path, client: LakeFS) -> None:
        if target.exists() and any(target.iterdir()) and not (target / MARKER).is_file():
            raise DatasetError(f"{target} is not empty and is not a kubecore dataset copy; pick another folder.")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix=target.name + ".part-", dir=target.parent))
        try:
            if download_prefixes(client, ref.repo, commit, DOWNLOAD_PREFIXES, tmp) == 0:
                raise DatasetError(f"{ref} holds no ultralytics files (data.yaml, images/, labels/).")
            _write_data_yaml(tmp / "data.yaml", tmp / "data.yaml", target.resolve())
            (tmp / MARKER).write_text(json.dumps({"repo": ref.repo, "commit": commit}))
            shutil.rmtree(target, ignore_errors=True)
            os.replace(tmp, target)  # atomic: a half-downloaded copy is never visible as complete
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


register(Format(NAME, UltralyticsCreator(), UltralyticsConsumer()))
