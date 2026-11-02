"""Reading a dataset another project shares: two fake lakeFS (own = project b, owner = project a)."""
import base64
import json

import pytest
import yaml

from conftest import write_dataset
from fake_lakefs import FakeLakeFS
from kubecore import cli, credentials, datasets
from kubecore.errors import AuthError, ConfigError, DatasetError
from kubecore.formats import get_format, local
from kubecore.lakefs import LakeFS

OWN_BASE = "http://b-lakefs.ml-b.svc.cluster.local"
A_ENDPOINT, A_URL = "http://a-lakefs.ml-a.svc.cluster.local", "https://lakefs-a.example"
PEERS = {"project": "b", "peers": [{"project": "a", "endpoint": A_ENDPOINT, "url": A_URL}]}
YOLO = {"kaos.kind": "dataset", "kaos.template": "ultralytics"}


def tree_of(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def lakes(mesh, tmp_path):
    """b (own) and a (owner) both hold a dataset-x at the SAME commit id, with different bytes."""
    own, owner = FakeLakeFS(OWN_BASE), FakeLakeFS(A_ENDPOINT)
    own.kaos["/kaos/v1/peers"] = (200, PEERS)
    own.add_repo("dataset-x", metadata=YOLO, files=tree_of(write_dataset(tmp_path / "own-x", images=("own",))))
    owner.add_repo("dataset-x", metadata=YOLO, files=tree_of(write_dataset(tmp_path / "a-x", images=("shared",))))
    owner.add_repo("dataset-raw", files={"a.txt": b"from a", "sub/b.txt": b"B"})
    own.tag("dataset-x", "v1")
    owner.tag("dataset-x", "v1")
    owner.tag("dataset-raw", "v1")
    assert own.head("dataset-x") == owner.head("dataset-x")            # the collision case
    mesh.update({OWN_BASE: own, A_ENDPOINT: owner, A_URL: owner})
    return own, owner


@pytest.fixture
def step_env(monkeypatch, zitadel_env):
    """A pipeline step of project b: own endpoint, own app key, machine key for peers."""
    monkeypatch.setenv("LAKEFS_ENDPOINT", OWN_BASE)
    monkeypatch.setenv("LAKEFS_ACCESS_KEY", "AK-B")
    monkeypatch.setenv("LAKEFS_SECRET_KEY", "SK-B")
    return zitadel_env


def object_gets(fake):
    return [c for c in fake.calls if c[0] == "GET" and c[1].endswith("/objects")]


SHARED = datasets.DatasetRef.parse("a/dataset-x@v1")
OWN_REF = datasets.DatasetRef.parse("dataset-x@v1")


def test_bytes_come_from_the_owner(lakes, step_env):
    own, owner = lakes
    data_yaml = datasets.materialize(SHARED)                         # LakeFS.connect(): the step's own lakeFS
    root = data_yaml.parent
    assert (root / "images/train/shared.jpg").read_bytes() == b"img-shared"
    assert not (root / "images/train/own.jpg").exists()
    assert object_gets(owner) and not object_gets(own)
    assert yaml.safe_load(data_yaml.read_text())["path"] == str(root.resolve())


def test_cache_path_and_marker_carry_the_owner(lakes, step_env, tmp_path):
    _, owner = lakes
    data_yaml = datasets.materialize(SHARED)
    commit = owner.head("dataset-x")
    assert data_yaml.parent == tmp_path / "cache" / "a" / "dataset-x" / commit
    marker = json.loads((data_yaml.parent / local.MARKER).read_text())
    assert marker == {"repo": "dataset-x", "commit": commit, "prefix": None, "owner": "a"}


def test_own_and_shared_dataset_x_never_collide(lakes, step_env, tmp_path):
    own, owner = lakes
    mine = datasets.materialize(OWN_REF).parent
    theirs = datasets.materialize(SHARED).parent
    assert mine == tmp_path / "cache" / "dataset-x" / own.head("dataset-x")
    assert theirs == tmp_path / "cache" / "a" / "dataset-x" / owner.head("dataset-x")
    assert (mine / "images/train/own.jpg").is_file() and not (mine / "images/train/shared.jpg").exists()
    assert (theirs / "images/train/shared.jpg").is_file() and not (theirs / "images/train/own.jpg").exists()
    assert json.loads((mine / local.MARKER).read_text())["owner"] is None
    n_own, n_owner = len(object_gets(own)), len(object_gets(owner))
    assert datasets.materialize(OWN_REF).parent == mine and datasets.materialize(SHARED).parent == theirs
    assert (len(object_gets(own)), len(object_gets(owner))) == (n_own, n_owner)   # both cached, nothing re-read


def test_a_shared_copy_in_an_explicit_dest_is_not_taken_for_the_own_one(lakes, step_env, tmp_path):
    own, _ = lakes
    dest = tmp_path / "work"
    datasets.materialize(SHARED, dest)
    datasets.materialize(OWN_REF, dest)                              # same dest, same commit id, other owner
    assert (dest / "images/train/own.jpg").is_file() and not (dest / "images/train/shared.jpg").exists()
    assert json.loads((dest / local.MARKER).read_text())["owner"] is None
    assert object_gets(own)


def test_the_owner_sees_only_bearer_tokens_never_the_access_key(lakes, step_env):
    own, owner = lakes
    datasets.materialize(SHARED)
    assert owner.auth and set(owner.auth) == {"Bearer minted-token"}
    basic = "Basic " + base64.b64encode(b"AK-B:SK-B").decode()
    assert own.auth and set(own.auth) == {basic}                     # the own lakeFS keeps the app key
    assert not any("AK-B" in a or basic.split()[1] in a for a in owner.auth)


def test_one_mint_per_client(lakes, step_env):
    c = LakeFS.connect()
    datasets.materialize(SHARED, client=c)
    datasets.materialize(datasets.DatasetRef.parse("a/dataset-raw@v1"), client=c)
    assert len(step_env.requests) == 1


def test_owner_endpoint_in_cluster_url_outside(lakes, step_env):
    _, owner = lakes
    datasets.materialize(SHARED)
    assert {c[1] for c in owner.calls}                               # reached through the in-cluster endpoint
    outside = FakeLakeFS("https://lakefs-b.example")
    outside.kaos["/kaos/v1/peers"] = (200, PEERS)
    assert datasets.source(SHARED, outside.client())[1].base_url == A_URL


def test_raw_shared_dataset_and_prefix(lakes, step_env, tmp_path):
    _, owner = lakes
    ref = datasets.DatasetRef.parse("a/dataset-raw@v1")
    whole = datasets.materialize(ref)
    assert (whole / "a.txt").read_bytes() == b"from a"
    assert whole.parent == tmp_path / "cache" / "a" / "dataset-raw"
    sub = datasets.materialize(ref, prefix="sub")
    assert (sub / "b.txt").read_bytes() == b"B" and sub.parent == whole.parent
    assert json.loads((sub / local.MARKER).read_text())["owner"] == "a"


def test_resolve_of_a_shared_ref_asks_the_owner(lakes, step_env):
    own, owner = lakes
    owner.repos["dataset-x"]["commits"]["cA-only"] = {"x": b"1"}
    owner.repos["dataset-x"]["branches"]["main"]["commit"] = "cA-only"
    assert datasets.resolve(datasets.DatasetRef.parse("a/dataset-x@latest")) == "cA-only"
    assert datasets.resolve(datasets.DatasetRef.parse("dataset-x@latest")) == own.head("dataset-x")


def test_consumer_called_directly_with_the_own_client(lakes, step_env):
    _, owner = lakes
    path = get_format("ultralytics").consumer.materialize(SHARED, None, LakeFS.connect())
    assert (path.parent / "images/train/shared.jpg").is_file() and object_gets(owner)


def test_pinned_shared_commit_downloads_that_commit_from_the_owner(lakes, step_env, tmp_path):
    _, owner = lakes
    pinned = owner.head("dataset-x")
    owner.repos["dataset-x"]["commits"]["cnewer000"] = {"data.yaml": b"names: [z]\ntrain: images/train\nval: images/val\n"}
    owner.repos["dataset-x"]["tags"]["v1"] = "cnewer000"            # the tag moved: the pin wins
    out = datasets.materialize(SHARED.with_commit(pinned), tmp_path / "pin")
    assert (tmp_path / "pin" / "images/train/shared.jpg").is_file() and out.is_file()


def test_owner_that_is_the_own_project_reads_the_own_lakefs(lakes, step_env, tmp_path):
    own, owner = lakes
    path = datasets.materialize(datasets.DatasetRef.parse("b/dataset-x@v1"))
    assert path.parent == tmp_path / "cache" / "dataset-x" / own.head("dataset-x")     # normalised: no owner
    assert (path.parent / "images/train/own.jpg").is_file() and not object_gets(owner)
    assert step_env.requests == []                                  # and no token minted


def test_unknown_owner(lakes, step_env):
    with pytest.raises(DatasetError, match="zz is not a project of your organisation"):
        datasets.materialize(datasets.DatasetRef.parse("zz/dataset-x@v1"))


def test_too_old_own_lakefs(lakes, step_env):
    own, _ = lakes
    own.kaos.pop("/kaos/v1/peers")
    with pytest.raises(ConfigError, match="too old"):
        datasets.materialize(SHARED)
    assert datasets.materialize(OWN_REF).is_file()                   # own datasets still work


def test_no_peer_credential_is_a_clear_error(lakes, monkeypatch):
    monkeypatch.setenv("LAKEFS_ENDPOINT", OWN_BASE)
    monkeypatch.setenv("LAKEFS_ACCESS_KEY", "AK-B")
    monkeypatch.setenv("LAKEFS_SECRET_KEY", "SK-B")
    _, owner = lakes
    with pytest.raises(AuthError, match="LAKEFS_ACCESS_KEY is never sent to another project"):
        datasets.materialize(SHARED)
    assert owner.calls == []


def test_not_shared_any_more_is_refused_by_the_owner(lakes, step_env):
    _, owner = lakes
    del owner.repos["dataset-x"]                                    # what an unshared dataset looks like to b
    with pytest.raises(DatasetError, match="dataset-x does not exist"):
        datasets.materialize(SHARED)


def test_staged_copy_used_only_for_the_same_owner(lakes, step_env, tmp_path, monkeypatch):
    _, owner = lakes
    commit = owner.head("dataset-x")
    staged = write_dataset(tmp_path / "lustre" / commit, images=("staged",))
    monkeypatch.setenv("KUBECORE_STAGED_DIR", str(staged))
    (staged / ".kaos-ready").write_text(json.dumps({"repo": "dataset-x", "commit": commit}))   # b's own copy
    data_yaml = datasets.materialize(SHARED)
    assert yaml.safe_load(data_yaml.read_text())["path"] != str(staged) and object_gets(owner)
    (staged / ".kaos-ready").write_text(json.dumps({"repo": "dataset-x", "commit": commit, "owner": "a"}))
    owner.calls.clear()
    data_yaml = datasets.materialize(SHARED, tmp_path / "out")
    assert yaml.safe_load(data_yaml.read_text())["path"] == str(staged) and not object_gets(owner)


def test_a_client_for_one_owner_refuses_another_owners_ref(lakes, step_env):
    a_client = LakeFS.connect().for_owner("a")
    with pytest.raises(DatasetError, match="this client reads project a"):
        datasets.source(datasets.DatasetRef.parse("c/dataset-x@v1"), a_client)
    assert datasets.source(SHARED, a_client) == (SHARED, a_client)


# ------------------------------------------------------------------ CLI pull of a shared ref
def test_cli_pull_of_a_shared_ref(lakes, step_env, capsys, tmp_path):
    _, owner = lakes
    dest = tmp_path / "local"
    code = cli.main(["dataset", "pull", "a/dataset-x@v1", str(dest)])
    out = capsys.readouterr().out
    assert code == 0 and f"Ready: {dest}/data.yaml" in out
    assert (dest / "images/train/shared.jpg").read_bytes() == b"img-shared"
    assert json.loads((dest / local.MARKER).read_text())["owner"] == "a"


def test_cli_pull_default_location_is_under_the_owner(lakes, step_env, capsys, tmp_path):
    _, owner = lakes
    assert cli.main(["dataset", "pull", "a/dataset-x@v1"]) == 0
    assert f"cache/a/dataset-x/{owner.head('dataset-x')}/data.yaml" in capsys.readouterr().out


@pytest.mark.parametrize("ref,fragment", [
    ("zz/dataset-x@v1", "zz is not a project of your organisation"),
    ("a/dataset-x@v9", "no version v9"),
    ("a/my-repo@main", "not a shared dataset"),
    ("A/dataset-x@v1", "not a project name"),
])
def test_cli_pull_errors_are_one_line(lakes, step_env, capsys, ref, fragment):
    code = cli.main(["dataset", "pull", ref])
    err = capsys.readouterr().err
    assert code == 1 and err.startswith("ERROR:") and fragment in err and err.count("\n") == 1


def test_laptop_uses_the_browser_session_for_the_peer(lakes, monkeypatch, tmp_path):
    own, owner = lakes
    monkeypatch.setenv("LAKEFS_ENDPOINT", OWN_BASE)
    credentials.save_session(OWN_BASE, "person-token")
    datasets.materialize(SHARED)
    assert set(owner.auth) == {"Bearer person-token"} and set(own.auth) == {"Bearer person-token"}
