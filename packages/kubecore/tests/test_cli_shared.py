"""``kubecore dataset list --shared``: own peers, then each peer's /kaos/v1/shared with the caller's token."""
import pytest

from fake_lakefs import FakeLakeFS
from kubecore import cli

OWN = FakeLakeFS.BASE        # "http://lakefs.test": not in the cluster, so the peers' public URLs are used
A, C, D, E = "https://lakefs-a.test", "https://lakefs-c.test", "https://lakefs-d.test", "https://lakefs-e.test"


def dataset(name, versions=(), description=""):
    return {"name": name, "description": description, "location": f"gs://bucket/{name}",
            "latest": "c-head", "versions": [{"tag": t, "commit": f"c-{t}"} for t in versions]}


@pytest.fixture
def peers_of_b(mesh, fake, monkeypatch):
    fake.kaos["/kaos/v1/peers"] = (200, {"project": "b", "peers": [
        {"project": "a", "endpoint": "http://a.svc", "url": A},
        {"project": "c", "endpoint": "http://c.svc", "url": C},
        {"project": "d", "endpoint": "http://d.svc", "url": D}]})
    fakes = {name: FakeLakeFS(url) for name, url in (("a", A), ("c", C), ("d", D))}
    for f in fakes.values():
        mesh[f.base] = f
    fakes["a"].kaos["/kaos/v1/shared"] = (200, {"owner": "a", "datasets": [
        dataset("dataset-zebra", ["v2", "v1"], "stripes"), dataset("dataset-cats", ["v3"], "cats of a")]})
    fakes["c"].kaos["/kaos/v1/shared"] = (401, {"message": "no consumer group"})
    # d: no endpoint at all -> 404 (an older lakeFS)
    monkeypatch.setattr(cli, "_connect", lambda args: fake.client())
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "b-token")
    return fakes


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_list_shared_lists_owner_refs_with_versions(capsys, peers_of_b):
    code, out, err = run(capsys, "dataset", "list", "--shared")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].split() == ["a/dataset-cats", "v3", "cats", "of", "a"]
    assert lines[1].split() == ["a/dataset-zebra", "v2,", "v1", "stripes"]
    assert "dataset = a/dataset-cats@v3" in out and "kubecore dataset pull a/dataset-cats@v3" in out
    assert "c/" not in out                                           # 401: nothing shared, no noise
    assert "c:" not in err
    assert "NOTE: d: its lakeFS is too old to share datasets" in err


def test_list_shared_asks_each_peer_with_the_callers_token(capsys, peers_of_b):
    run(capsys, "dataset", "list", "--shared")
    for f in peers_of_b.values():
        assert f.calls == [("GET", "/kaos/v1/shared")] and f.auth == ["Bearer b-token"]


def test_list_shared_with_nothing_shared(capsys, peers_of_b):
    peers_of_b["a"].kaos["/kaos/v1/shared"] = (401, {})
    code, out, _ = run(capsys, "dataset", "list", "--shared")
    assert code == 0 and "No datasets are shared with your project yet" in out


def test_list_shared_with_no_peers(capsys, peers_of_b, fake):
    fake.kaos["/kaos/v1/peers"] = (200, {"project": "b", "peers": []})
    code, out, _ = run(capsys, "dataset", "list", "--shared")
    assert code == 0 and "No datasets are shared" in out


def test_list_shared_without_versions_hints_latest(capsys, peers_of_b):
    peers_of_b["a"].kaos["/kaos/v1/shared"] = (200, {"owner": "a", "datasets": [dataset("dataset-new")]})
    code, out, _ = run(capsys, "dataset", "list", "--shared")
    assert code == 0 and "a/dataset-new" in out and "no versions" in out
    assert "kubecore dataset pull a/dataset-new@latest" in out


def test_list_shared_skips_non_datasets_and_strips_owner_prefixes(capsys, peers_of_b):
    peers_of_b["a"].kaos["/kaos/v1/shared"] = (200, {"owner": "a", "datasets": [
        dataset("outputs-app", ["v1"]), dataset("a/dataset-pre", ["v1"])]})
    _, out, _ = run(capsys, "dataset", "list", "--shared")
    assert "outputs-app" not in out and "a/dataset-pre" in out and "a/a/" not in out


@pytest.mark.parametrize("answer,note", [
    ((500, {"message": "boom"}), "its lakeFS answered HTTP 500"),
    ((403, {"message": "no"}), "its lakeFS answered HTTP 403"),
    ((200, b"<html>lakeFS</html>"), "its lakeFS is too old"),          # an old lakeFS's web UI
    ((200, {"datasets": "nope"}), "its lakeFS is too old"),
])
def test_list_shared_survives_a_bad_peer(capsys, peers_of_b, answer, note):
    peers_of_b["c"].kaos["/kaos/v1/shared"] = answer
    code, out, err = run(capsys, "dataset", "list", "--shared")
    assert code == 0 and "a/dataset-cats" in out and f"NOTE: c: {note}" in err


def test_list_shared_survives_an_unreachable_peer(capsys, peers_of_b, mesh):
    del mesh[C]                                                      # c's URL resolves nowhere
    peers_of_b["c"].kaos.clear()
    import requests

    class Down(FakeLakeFS):
        def send(self, request, **kw):
            raise requests.ConnectionError("down")
    mesh[C] = Down(C)
    code, out, err = run(capsys, "dataset", "list", "--shared")
    assert code == 0 and "a/dataset-cats" in out and "NOTE: c: cannot reach its lakeFS (ConnectionError)" in err


def test_list_shared_on_an_old_own_lakefs(capsys, peers_of_b, fake):
    fake.kaos.pop("/kaos/v1/peers")
    code, _, err = run(capsys, "dataset", "list", "--shared")
    assert code == 1 and "too old for datasets shared between projects" in err and err.count("\n") == 1


def test_list_shared_without_a_peer_token(capsys, peers_of_b, monkeypatch):
    monkeypatch.delenv("LAKEFS_BEARER_TOKEN")
    monkeypatch.setenv("LAKEFS_ACCESS_KEY", "AK-B")
    monkeypatch.setenv("LAKEFS_SECRET_KEY", "SK-B")
    code, _, err = run(capsys, "dataset", "list", "--shared")
    assert code == 1 and "never sent to another project" in err
    assert all(f.calls == [] for f in peers_of_b.values())


def test_list_without_shared_is_unchanged(capsys, peers_of_b):
    code, out, _ = run(capsys, "dataset", "list")
    assert code == 0 and "dataset-default" in out and all(f.calls == [] for f in peers_of_b.values())
