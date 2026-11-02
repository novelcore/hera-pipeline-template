"""Shared fixtures: a fake lakeFS, a clean environment, and a sample ultralytics dataset on disk."""
from __future__ import annotations

import json

import pytest

from fake_lakefs import FakeLakeFS

ENV_VARS = ("LAKEFS_ENDPOINT", "LAKEFS_URL", "LAKEFS_ACCESS_KEY", "LAKEFS_SECRET_KEY", "LAKEFS_BEARER_TOKEN",
            "KUBECORE_STAGED_DIR", "KUBECORE_CACHE_DIR", "KUBECORE_DATASET_CONFIG",
            "KUBECORE_STORAGE_NAMESPACE_BASE", "KUBECORE_ML_OIDC_ISSUER", "KUBECORE_ML_OIDC_CLIENT_ID",
            "KUBECORE_ML_OIDC_PROJECT_ID", "ZITADEL_MACHINE_KEY_FILE", "ZITADEL_DOMAIN",
            "ZITADEL_MLFLOW_PROJECT_ID")


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("KUBECORE_ML_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("KUBECORE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    from kubecore import config, peers
    config.load_config.cache_clear()
    peers.clear_cache()


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


@pytest.fixture
def mesh(monkeypatch):
    """``{base URL: FakeLakeFS}``: every client the package builds itself (``for_owner``, ``connect``) is routed
    to the fake registered for its base URL, through the real session code (auth headers included)."""
    from kubecore import lakefs
    fakes: dict = {}
    real = lakefs._session

    def session(cred, pool):
        s = real(cred, pool)
        for base, fake_lakefs in fakes.items():
            s.mount(base, fake_lakefs)
        return s

    monkeypatch.setattr(lakefs, "_session", session)
    return fakes


_RSA = {}


def rsa_key():
    """One 2048-bit RSA key per test session: (private PEM, public key)."""
    if not _RSA:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        _RSA["pem"] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                        serialization.NoEncryption()).decode()
        _RSA["public"] = key.public_key()
    return _RSA["pem"], _RSA["public"]


def write_machine_key(path, **overrides):
    """A Zitadel JSON machine key file (``type``, ``keyId``, ``key``, ``userId``)."""
    key = {"type": "serviceaccount", "keyId": "kid-123", "key": rsa_key()[0], "userId": "user-456", **overrides}
    path.write_text(json.dumps({k: v for k, v in key.items() if v is not None}))
    return path


@pytest.fixture
def zitadel_env(tmp_path, monkeypatch):
    """Machine-key env of a pipeline step, and a fake Zitadel token endpoint behind ``zitadel._session``."""
    import requests
    from fake_zitadel import FakeTokenEndpoint
    from kubecore import zitadel
    endpoint = FakeTokenEndpoint()
    monkeypatch.setenv("ZITADEL_MACHINE_KEY_FILE", str(write_machine_key(tmp_path / "machine-key.json")))
    monkeypatch.setenv("ZITADEL_DOMAIN", "zitadel.test")
    monkeypatch.setenv("ZITADEL_MLFLOW_PROJECT_ID", "321")

    def session():
        s = requests.Session()
        s.mount("https://zitadel.test", endpoint)
        return s

    monkeypatch.setattr(zitadel, "_session", session)
    return endpoint
