"""peers: the own lakeFS's /kaos/v1/peers, address choice, unknown owners, old servers, the per-process cache."""
import pytest

from fake_lakefs import FakeLakeFS
from kubecore import credentials, peers
from kubecore.errors import AuthError, ConfigError, DatasetError, LakeFSError
from kubecore.lakefs import LakeFS

OWN_SVC = "http://b-lakefs.ml-b.svc.cluster.local:80"
A_ENDPOINT, A_URL = "http://a-lakefs.ml-a.svc.cluster.local:80", "https://lakefs-a.example"
DOC = {"project": "b", "peers": [{"project": "a", "endpoint": A_ENDPOINT, "url": A_URL},
                                 {"project": "c", "endpoint": "http://c-lakefs.ml-c.svc.cluster.local",
                                  "url": "https://lakefs-c.example"}]}


@pytest.fixture
def own():
    f = FakeLakeFS(OWN_SVC)
    f.kaos["/kaos/v1/peers"] = (200, DOC)
    return f


def peer_calls(fake):
    return [c for c in fake.calls if c[1] == "/kaos/v1/peers"]


def test_load_reads_the_peers_document(own):
    found = peers.load(own.client())
    assert found.project == "b"
    assert found.peers == (peers.Peer("a", A_ENDPOINT, A_URL),
                           peers.Peer("c", "http://c-lakefs.ml-c.svc.cluster.local", "https://lakefs-c.example"))


def test_load_is_cached_once_per_process(own, monkeypatch):
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "b-token")
    peers.load(own.client())
    peers.load(own.client())                         # a second client to the same lakeFS
    own.client().for_owner("a")
    own.client().for_owner("c")
    assert len(peer_calls(own)) == 1


def test_cache_is_per_lakefs():
    one, two = FakeLakeFS("http://one.test"), FakeLakeFS("http://two.test")
    one.kaos["/kaos/v1/peers"] = (200, {"project": "one", "peers": []})
    two.kaos["/kaos/v1/peers"] = (200, {"project": "two", "peers": []})
    assert (peers.load(one.client()).project, peers.load(two.client()).project) == ("one", "two")


def test_load_sends_the_own_credential(own):
    peers.load(own.client(bearer="own-token"))
    assert own.auth == ["Bearer own-token"]


@pytest.mark.parametrize("base,expected", [
    ("http://b-lakefs.ml-b.svc.cluster.local:80", A_ENDPOINT),
    ("http://b-lakefs.ml-b.svc.cluster.local", A_ENDPOINT),
    ("http://b-lakefs.ml-b.svc:8000", A_ENDPOINT),
    ("http://B-LAKEFS.ML-B.SVC.CLUSTER.LOCAL", A_ENDPOINT),
    ("https://lakefs-b.example", A_URL),
    ("https://svc.example.com", A_URL),            # "svc" in the name is not a Service address
    ("https://lakefs.svc.example.com", A_URL),
    ("http://localhost:8000", A_URL),              # a port-forward on a laptop
    ("http://10.0.0.7:80", A_URL),
])
def test_base_for_endpoint_in_cluster_else_url(base, expected):
    assert peers.base_for(base, peers.Peer("a", A_ENDPOINT, A_URL)) == expected


def test_base_for_falls_back_and_explains():
    assert peers.base_for(OWN_SVC, peers.Peer("a", "", A_URL + "/")) == A_URL     # in cluster, no endpoint
    with pytest.raises(DatasetError, match="project a's lakeFS has no public URL"):
        peers.base_for("https://lakefs-b.example", peers.Peer("a", A_ENDPOINT, ""))


def test_unknown_owner_is_a_clear_error(own):
    with pytest.raises(DatasetError) as err:
        peers.peer(own.client(), "zz")
    assert "zz is not a project of your organisation" in str(err.value) and "projects: a, c" in str(err.value)


def test_unknown_owner_with_no_peers(own):
    own.kaos["/kaos/v1/peers"] = (200, {"project": "b", "peers": []})
    with pytest.raises(DatasetError, match=r"\(projects: none\)"):
        peers.peer(own.client(), "a")


@pytest.mark.parametrize("answer", [
    (404, b"<html><body>404 page not found</body></html>"),       # no such endpoint
    (200, b"<!DOCTYPE html><html><head><title>lakeFS</title>"),     # an old lakeFS serves its web UI
    (200, b""),
    (200, ["not", "an", "object"]),
    (200, {"project": "b", "peers": "nope"}),
    (405, b"method not allowed"),
])
def test_old_lakefs_is_too_old(own, answer):
    own.kaos["/kaos/v1/peers"] = answer
    with pytest.raises(ConfigError, match=f"lakeFS at {OWN_SVC} is too old for datasets shared"):
        peers.load(own.client())


def test_a_failed_load_is_not_cached(own):
    own.kaos["/kaos/v1/peers"] = (404, b"")
    with pytest.raises(ConfigError):
        peers.load(own.client())
    own.kaos["/kaos/v1/peers"] = (200, DOC)
    assert peers.load(own.client()).project == "b"


@pytest.mark.parametrize("status,err,fragment", [
    (401, AuthError, "kubecore login"),
    (302, AuthError, "kubecore login"),          # oauth2-proxy sends an unauthenticated caller to the login page
    (403, AuthError, "not allowed"),
    (500, LakeFSError, "HTTP 500"),
])
def test_load_errors(own, status, err, fragment):
    own.kaos["/kaos/v1/peers"] = (status, {"message": "x"})
    with pytest.raises(err, match=fragment):
        peers.load(own.client())


def test_peers_without_a_project_are_skipped(own):
    own.kaos["/kaos/v1/peers"] = (200, {"project": "b", "peers": [{"url": "https://x"}, "junk", {"project": "a"}]})
    assert [p.project for p in peers.load(own.client()).peers] == ["a"]


# ------------------------------------------------------------------ LakeFS.for_owner
def test_for_owner_builds_a_bearer_client_for_the_peer(own, monkeypatch):
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "b-token")
    c = own.client().for_owner("a")
    assert (c.base_url, c.owner) == (A_ENDPOINT, "a")
    assert c.session.headers["Authorization"] == "Bearer b-token" and c.session.auth is None


def test_for_owner_outside_the_cluster_uses_the_url(monkeypatch):
    f = FakeLakeFS("https://lakefs-b.example")
    f.kaos["/kaos/v1/peers"] = (200, DOC)
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "b-token")
    assert f.client().for_owner("a").base_url == A_URL


def test_for_owner_of_the_own_project_is_the_same_client(own):
    c = own.client()
    assert c.for_owner("b") is c


def test_for_owner_is_cached_per_client(own, monkeypatch):
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "b-token")
    c = own.client()
    assert c.for_owner("a") is c.for_owner("a") and c.for_owner("a") is not c.for_owner("c")


def test_for_owner_unknown_owner(own):
    with pytest.raises(DatasetError, match="zz is not a project of your organisation"):
        own.client().for_owner("zz")


def test_a_peer_client_cannot_hop_to_another_peer(own, monkeypatch):
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "b-token")
    with pytest.raises(LakeFSError, match="this client reads project a"):
        own.client().for_owner("a").for_owner("c")


def test_for_owner_never_carries_the_access_key(own, monkeypatch):
    monkeypatch.setenv("LAKEFS_ACCESS_KEY", "AK-B")
    monkeypatch.setenv("LAKEFS_SECRET_KEY", "SK-B")
    own_client = LakeFS(OWN_SVC, credentials.resolve(OWN_SVC), session=own.client().session)
    with pytest.raises(AuthError, match="LAKEFS_ACCESS_KEY is never sent to another project"):
        own_client.for_owner("a")
