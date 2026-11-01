"""Fixtures: the package's in-memory lakeFS, and a guard against the vendored engine shadowing the package."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kubecore" / "tests"))  # fake_lakefs.py

import kubecore  # noqa: E402

if not (Path(kubecore.__path__[0]) / "datasets.py").is_file():
    raise pytest.UsageError(
        "`kubecore` resolved to the vendored engine, not the package. Run `pytest step_tests` "
        "(not `python -m pytest`) with the package installed: pip install ./packages/kubecore")

from fake_lakefs import FakeLakeFS  # noqa: E402

ENV_VARS = ("LAKEFS_ENDPOINT", "LAKEFS_URL", "LAKEFS_ACCESS_KEY", "LAKEFS_SECRET_KEY", "LAKEFS_BEARER_TOKEN",
            "KUBECORE_STAGED_DIR", "KUBECORE_CACHE_DIR", "KUBECORE_DATASET_CONFIG", "CHECKPOINT_BUCKET",
            "KUBECORE_RUN_ID")


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("KUBECORE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def fake():
    f = FakeLakeFS()
    data = {"data.yaml": b"path: .\ntrain: images/train\nval: images/val\nnc: 2\nnames:\n  0: a\n  1: b\n",
            "images/train/x.jpg": b"img", "labels/train/x.txt": b"0 0.5 0.5 0.1 0.1\n"}
    f.add_repo("dataset-default", metadata={"kaos.kind": "dataset", "kaos.template": "ultralytics"}, files=data)
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
