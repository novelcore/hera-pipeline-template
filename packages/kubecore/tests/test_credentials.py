"""One credential chain: access key > bearer env > cached login session; URL discovery."""
import os
import stat

import pytest

from kubecore import config, credentials
from kubecore.errors import AuthError, ConfigError
from kubecore.lakefs import LakeFS

URL = "https://lakefs.example"


def test_chain_prefers_access_key_over_bearer_over_session(monkeypatch):
    credentials.save_session(URL, "session-token")
    assert credentials.resolve(URL).token == "session-token"
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "env-token")
    assert credentials.resolve(URL).token == "env-token"
    monkeypatch.setenv("LAKEFS_ACCESS_KEY", "AK")
    monkeypatch.setenv("LAKEFS_SECRET_KEY", "SK")
    cred = credentials.resolve(URL)
    assert (cred.access_key, cred.secret_key, cred.token) == ("AK", "SK", None)


def test_access_key_needs_both_halves(monkeypatch):
    monkeypatch.setenv("LAKEFS_ACCESS_KEY", "AK")
    with pytest.raises(AuthError, match="kubecore login"):
        credentials.resolve(URL)


def test_session_is_per_url_and_private():
    credentials.save_session(URL, "t")
    assert credentials.load_session("https://other.example") is None
    assert credentials.load_session(URL + "/").token == "t"
    assert stat.S_IMODE(os.stat(credentials.session_path()).st_mode) == 0o600


def test_client_sends_bearer_or_basic():
    bearer = LakeFS(URL, credentials.Credential(token="tok"))
    assert bearer.session.headers["Authorization"] == "Bearer tok"
    basic = LakeFS(URL, credentials.Credential(access_key="AK", secret_key="SK"))
    assert basic.session.auth == ("AK", "SK") and "Authorization" not in basic.session.headers


def test_endpoint_precedence(tmp_path, monkeypatch):
    (tmp_path / ".kubecore").mkdir()
    (tmp_path / ".kubecore" / "dataset-config.yaml").write_text("lakefsUrl: https://from-config/\n")
    config.load_config.cache_clear()
    assert config.resolve_endpoint() == "https://from-config"
    monkeypatch.setenv("LAKEFS_URL", "https://from-url-env/")
    assert config.resolve_endpoint() == "https://from-url-env"
    monkeypatch.setenv("LAKEFS_ENDPOINT", "https://from-endpoint-env")
    assert config.resolve_endpoint() == "https://from-endpoint-env"
    assert config.resolve_endpoint("https://flag/") == "https://flag"


def test_endpoint_missing():
    with pytest.raises(ConfigError):
        config.resolve_endpoint()
