"""Fixtures: kaos-lib's in-memory lakeFS (vendored as fake_lakefs.py) for the step code's tests."""
import importlib.util
from pathlib import Path

import pytest

try:
    import kaos_lib  # noqa: F401
except ImportError:
    raise pytest.UsageError("step tests need kaos-lib: see step_tests/README.md for the pip install line") from None

from fake_lakefs import FakeLakeFS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

ENV_VARS = ("LAKEFS_ENDPOINT", "LAKEFS_URL", "LAKEFS_ACCESS_KEY", "LAKEFS_SECRET_KEY", "LAKEFS_BEARER_TOKEN",
            "KAOS_STAGED_DIR", "KAOS_CACHE_DIR", "KAOS_DATASET_CONFIG", "CHECKPOINT_BUCKET",
            "KAOS_RUN_ID",
            # deprecated aliases, still read by a kaos-lib older than the rename
            "KUBECORE_STAGED_DIR", "KUBECORE_CACHE_DIR", "KUBECORE_DATASET_CONFIG", "KUBECORE_RUN_ID")


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("KAOS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("KUBECORE_CACHE_DIR", str(tmp_path / "cache"))  # deprecated alias
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def fake():
    f = FakeLakeFS()
    data = {"data.yaml": b"path: .\ntrain: images/train\nval: images/val\nnc: 2\nnames:\n  0: a\n  1: b\n",
            "images/train/x.jpg": b"img", "labels/train/x.txt": b"0 0.5 0.5 0.1 0.1\n"}
    f.add_repo("dataset-default", metadata={"kaos.kind": "dataset", "kaos.template": "yolo"}, files=data)
    f.tag("dataset-default", "v1")
    f.add_repo("outputs-myapp", metadata={"kaos.kind": "outputs"})
    return f


@pytest.fixture
def client(fake):
    return fake.client()


def load_step(step_dir: str):
    """Import steps/<step_dir>/app/entry.py under a unique module name (every step calls it `app.entry`)."""
    path = ROOT / "steps" / step_dir / "app" / "entry.py"
    spec = importlib.util.spec_from_file_location(f"step_{step_dir}_entry", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
