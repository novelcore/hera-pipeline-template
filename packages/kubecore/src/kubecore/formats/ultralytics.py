"""The ``ultralytics`` dataset format: the YOLO layout Ultralytics reads.

    data.yaml                path / train / val / test / names (nc optional) / kpt_shape for pose
    images/{train,val,test}/ the images
    labels/{train,val,test}/ one <image-stem>.txt per image: "<class-id> <x> <y> <w> <h>" lines, coords in [0,1];
                             pose adds K*D keypoint values (kpt_shape [K, D], visibility 0/1/2 when D=3);
                             segmentation lines are "<class-id> x1 y1 x2 y2 ..." (even count >= 6)

``UltralyticsCreator`` builds, validates and publishes; ``UltralyticsConsumer``
materializes a pinned version for training. Registered as ``ultralytics``.
"""
from __future__ import annotations

import json
import pathlib

from typing import Optional, Sequence

import yaml

from .. import datasets
from ..errors import DatasetError, ValidationFailed
from ..lakefs import LakeFS
from . import Format, ValidationReport, local, register

NAME = "ultralytics"
SPLITS = ("train", "val", "test")
REQUIRED_SPLITS = ("train", "val")  # Ultralytics trains on train and validates on val; test is optional
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
DOWNLOAD_PREFIXES = ("data.yaml", "images/", "labels/")  # everything training reads, nothing else


# --------------------------------------------------------------------- validation
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
    """Check names/nc; returns the class count labels are checked against.

    ``names`` is required; ``nc`` is optional (Ultralytics derives it) and is compared with
    ``names`` only when both are present.
    """
    nc, names = data.get("nc"), data.get("names")
    if nc is not None and (isinstance(nc, bool) or not isinstance(nc, int) or nc < 1):
        errors.append(f"data.yaml: nc must be a positive integer (got {nc!r})")
        nc = None
    if isinstance(names, dict):
        names = _names_from_mapping(names, errors)
    if not isinstance(names, list) or not names:
        errors.append("data.yaml: names must be a non-empty list (or an id -> name mapping)")
        return nc
    if nc is not None and nc != len(names):
        errors.append(f"data.yaml: nc is {nc} but names has {len(names)} entries")
    return nc if nc is not None else len(names)


def _kpt_shape(data: dict, errors: list) -> Optional[tuple]:
    """(K, D) of a pose dataset from ``kpt_shape: [K, D]``, or None for detection/segmentation."""
    shape = data.get("kpt_shape")
    if shape is None:
        return None
    ok = (isinstance(shape, list) and len(shape) == 2
          and all(isinstance(v, int) and not isinstance(v, bool) for v in shape)
          and shape[0] >= 1 and shape[1] in (2, 3))
    if not ok:
        errors.append(f"data.yaml: kpt_shape must be [K, D] with K >= 1 keypoints and D 2 or 3 (got {shape!r})")
        return None
    return shape[0], shape[1]


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


def _line_problems(parts: list, nc: Optional[int], kpt: Optional[tuple]) -> list:
    """Problems of one label line (already split). Detection, polygon (segmentation) or pose."""
    if kpt:
        k, d = kpt
        if len(parts) != 5 + k * d:
            return [f"expected '<class-id> <x> <y> <w> <h>' + {k} keypoints x {d} values "
                    f"({5 + k * d} values), got {len(parts)}"]
    elif len(parts) != 5 and not (len(parts) >= 7 and len(parts) % 2 == 1):
        return [f"expected '<class-id> <x> <y> <w> <h>' (detection) or '<class-id> x1 y1 x2 y2 ...' "
                f"(segmentation: an even number >= 6 of coordinates), got {len(parts)} values"]
    try:
        cid, vals = int(parts[0]), [float(p) for p in parts[1:]]
    except ValueError:
        return ["class id must be an integer and the rest numbers"]
    problems = []
    if cid < 0 or (nc is not None and cid >= nc):
        problems.append(f"class id {cid} is outside 0..{(nc or 1) - 1}")
    if kpt and kpt[1] == 3:
        coords = vals[:4] + [v for i, v in enumerate(vals[4:]) if i % 3 != 2]
        vis = [v for i, v in enumerate(vals[4:]) if i % 3 == 2]
        if any(v not in (0.0, 1.0, 2.0) for v in vis):
            problems.append("keypoint visibility must be 0, 1 or 2")
    else:
        coords = vals
    if any(not 0.0 <= c <= 1.0 for c in coords):
        problems.append("coordinates must be within [0,1]")
    return problems


def _check_label_file(label: pathlib.Path, rel: str, nc: Optional[int], kpt: Optional[tuple], errors: list) -> None:
    for n, line in enumerate(label.read_text().splitlines(), 1):
        if line.strip():
            for problem in _line_problems(line.split(), nc, kpt):
                errors.append(f"{rel}:{n}: {problem}: {line.strip()[:80]!r}")


def _check_split(root: pathlib.Path, split: str, dirs: tuple, nc: Optional[int], kpt: Optional[tuple],
                 errors: list) -> None:
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
            _check_label_file(label, rel, nc, kpt, errors)


def validate(local_dir) -> ValidationReport:
    """Check a local dataset directory against the format; collects all problems."""
    root, errors = pathlib.Path(local_dir), []
    if not root.is_dir():
        return ValidationReport([f"{root} is not a directory"])
    data = _load_data_yaml(root, errors)
    if data is not None:
        nc, kpt = _check_classes(data, errors), _kpt_shape(data, errors)
        for split in SPLITS:
            dirs = _split_dirs(data, split, errors)
            if dirs:
                _check_split(root, split, dirs, nc, kpt, errors)
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
                description: str = "", validate_first: bool = True, metadata: Optional[dict] = None,
                client: Optional[LakeFS] = None) -> datasets.PublishResult:
        """Validate, then upload ``local_dir`` to ``repo`` through a draft branch and a pull request.

        Creates ``repo`` first when missing (labels kaos.kind=dataset, kaos.template=ultralytics).
        Raises ValidationFailed with every problem when the dataset is invalid
        (``validate_first=False`` skips the check). ``metadata`` is recorded on the commit.
        """
        if validate_first:
            report = validate(local_dir)
            if not report.ok:
                raise ValidationFailed(report.errors)
        labels = {datasets.LABEL_KIND: "dataset", datasets.LABEL_TEMPLATE: NAME}
        if description:
            labels[datasets.LABEL_DESCRIPTION] = description
        return datasets.publish_tree(local_dir, repo, message, via_pull_request, labels, client, metadata)


# --------------------------------------------------------------------- consumer
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

    def materialize(self, ref: datasets.DatasetRef, dest=None, client: Optional[LakeFS] = None,
                    commit: Optional[str] = None, prefix: Optional[str] = None) -> pathlib.Path:
        """Local ``data.yaml`` Ultralytics can train on for ``ref``.

        Only data.yaml, images/ and labels/ are downloaded, at the pinned commit. Data lives in
        ``dest`` (default ``<cache>/<repo>/<commit>``); a second call for the same commit is free.
        ``commit`` (or ``ref.commit``) pins the version. A staged copy (KUBECORE_STAGED_DIR holding
        the commit) is used in place, nothing downloaded. ``prefix`` is only for the raw format.
        """
        if prefix:
            raise DatasetError("prefix= is only supported by the raw format (fmt_name='raw').")
        commit = datasets.resolve(ref, client, commit)
        target = pathlib.Path(dest) if dest else local.cache_dir(ref.repo, commit)
        staged = local.staged_dir(commit, "data.yaml")
        if staged:
            return _write_data_yaml(staged / "data.yaml", target / "data.yaml", staged)
        if local.marker_matches(target, ref.repo, commit, None, "data.yaml"):
            return target / "data.yaml"
        local.fetch(client, ref.repo, commit, DOWNLOAD_PREFIXES, target,
                    finalize=lambda tmp: _write_data_yaml(tmp / "data.yaml", tmp / "data.yaml", target.resolve()),
                    empty_message=f"{ref} holds no ultralytics files (data.yaml, images/, labels/).")
        return target / "data.yaml"


register(Format(NAME, UltralyticsCreator(), UltralyticsConsumer()))
