"""Shared fixtures: a fake lakeFS, a clean environment, and a sample ultralytics dataset on disk."""
from __future__ import annotations

import pytest

from fake_lakefs import FakeLakeFS

ENV_VARS = ("LAKEFS_ENDPOINT", "LAKEFS_URL", "LAKEFS_ACCESS_KEY", "LAKEFS_SECRET_KEY", "LAKEFS_BEARER_TOKEN",
            "KUBECORE_STAGED_DIR", "KUBECORE_CACHE_DIR", "KUBECORE_DATASET_CONFIG",
            "KUBECORE_STORAGE_NAMESPACE_BASE", "KUBECORE_ML_OIDC_ISSUER", "KUBECORE_ML_OIDC_CLIENT_ID",
            "KUBECORE_ML_OIDC_PROJECT_ID")


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("KUBECORE_ML_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("KUBECORE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    from kubecore import config
    config.load_config.cache_clear()


@pytest.fixture
def fake():
    f = FakeLakeFS()
    f.add_repo("dataset-default", metadata={"kaos.kind": "dataset", "kaos.template": "ultralytics",
                                            "kaos.default": "true"})
    f.add_repo("outputs-myapp", metadata={"kaos.kind": "outputs", "kaos.app": "myapp"})
    return f


@pytest.fixture
def client(fake):
    return fake.client()


def write_dataset(root, nc=2, images=("a", "b"), bad_label=None, skip_label=None):
    """A valid ultralytics dataset in ``root`` (train + val), with optional damage."""
    names = "\n".join(f"  {i}: c{i}" for i in range(nc))
    root.mkdir(parents=True, exist_ok=True)
    (root / "data.yaml").write_text(
        f"path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnc: {nc}\nnames:\n{names}\n")
    for split in ("train", "val"):
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        (root / "labels" / split).mkdir(parents=True, exist_ok=True)
        for stem in images:
            (root / "images" / split / f"{stem}.jpg").write_bytes(b"img-" + stem.encode())
            if (split, stem) != skip_label:
                line = bad_label if bad_label and (split, stem) == ("train", "a") else "0 0.5 0.5 0.2 0.2"
                (root / "labels" / split / f"{stem}.txt").write_text(line + "\n")
    return root


@pytest.fixture
def dataset_dir(tmp_path):
    return write_dataset(tmp_path / "ds")
