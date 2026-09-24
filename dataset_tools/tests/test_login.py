"""login.py tests: where the OIDC settings come from, the session cache, and the
order the CLI tries things in (cache -> browser login -> opt-in paste)."""
from __future__ import annotations

import json

import pytest

from dataset_cli import appconfig, login


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(login, "SESSION_PATH", tmp_path / "session.json")
    for var in ("KUBECORE_ML_OIDC_ISSUER", "KUBECORE_ML_OIDC_CLIENT_ID",
                "KUBECORE_ML_OIDC_PROJECT_ID", "KUBECORE_DATASET_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    appconfig.load_config.cache_clear()
    yield
    appconfig.load_config.cache_clear()


def _write_config(tmp_path, **values):
    (tmp_path / ".kubecore").mkdir(exist_ok=True)
    (tmp_path / ".kubecore" / "dataset-config.yaml").write_text(
        "".join(f"{k}: '{v}'\n" for k, v in values.items()))
    appconfig.load_config.cache_clear()


def test_oidc_settings_read_from_app_repo_config(tmp_path):
    """The render step writes these into the app repo; that is the only way the
    CLI learns which Zitadel app to use."""
    _write_config(tmp_path, oidcIssuer="https://z.example", oidcClientId="cid",
                  oidcProjectId="proj")
    assert login.oidc_settings() == ("https://z.example", "cid", "proj")


def test_env_overrides_config(tmp_path, monkeypatch):
    _write_config(tmp_path, oidcIssuer="https://z.example", oidcClientId="cid")
    monkeypatch.setenv("KUBECORE_ML_OIDC_CLIENT_ID", "from-env")
    assert login.oidc_settings()[1] == "from-env"


def test_browser_login_not_attempted_without_config(monkeypatch):
    """No OIDC settings (project not provisioned yet) must not start a login it
    cannot finish; the caller then offers the paste fallback."""
    called = []
    monkeypatch.setattr(login.oidc_login, "login", lambda *a, **k: called.append(1))
    assert login.browser_login() is None
    assert called == []


def test_browser_login_returns_bearer(tmp_path, monkeypatch):
    _write_config(tmp_path, oidcIssuer="https://z.example", oidcClientId="cid",
                  oidcProjectId="proj")
    seen = {}

    def fake_login(issuer, client_id, audience_project_id=None):
        seen.update(issuer=issuer, client_id=client_id, aud=audience_project_id)
        return {"access_token": "tok"}

    monkeypatch.setattr(login.oidc_login, "login", fake_login)
    cred = login.browser_login()
    assert cred == login.Credential(token="tok")
    assert seen == {"issuer": "https://z.example", "client_id": "cid", "aud": "proj"}


def test_browser_login_failure_is_reported_not_raised(tmp_path, monkeypatch, capsys):
    _write_config(tmp_path, oidcIssuer="https://z.example", oidcClientId="cid")

    def boom(*a, **k):
        raise login.oidc_login.LoginError("sign-in failed: access_denied - ")

    monkeypatch.setattr(login.oidc_login, "login", boom)
    assert login.browser_login() is None
    assert "access_denied" in capsys.readouterr().out


def test_login_uses_browser_token_and_caches_it(tmp_path, monkeypatch):
    _write_config(tmp_path, oidcIssuer="https://z.example", oidcClientId="cid")
    monkeypatch.setattr(login.oidc_login, "login", lambda *a, **k: {"access_token": "tok"})
    monkeypatch.setattr(login.LakeFSClient, "check_auth", lambda self: True)
    # The paste path must never be reached when the browser login works.
    monkeypatch.setattr(login, "guided_paste_login",
                        lambda *a: pytest.fail("pasted despite a working browser login"))

    cred = login.login("https://lakefs.example")
    assert cred.token == "tok"
    cached = json.loads(login.SESSION_PATH.read_text())
    assert cached == {"base_url": "https://lakefs.example", "token": "tok"}


def test_legacy_cookie_cache_still_loads(monkeypatch):
    """A session cached by an older CLI ({"cookie": ...}) survives the upgrade."""
    login.SESSION_PATH.write_text(json.dumps(
        {"base_url": "https://lakefs.example", "cookie": "c00kie"}))
    monkeypatch.setattr(login.LakeFSClient, "check_auth", lambda self: True)
    assert login.load_session("https://lakefs.example") == login.Credential(cookie="c00kie")


def test_expired_cache_is_ignored(monkeypatch):
    login.SESSION_PATH.write_text(json.dumps(
        {"base_url": "https://lakefs.example", "token": "old"}))
    monkeypatch.setattr(login.LakeFSClient, "check_auth", lambda self: False)
    assert login.load_session("https://lakefs.example") is None
