"""The other projects of the organisation whose shared datasets this project can read (F-12).

The own kaos-lake serves them at ``GET /kaos/v1/peers``:
``{"project": "<own>", "peers": [{"project", "endpoint", "url"}]}``. ``endpoint`` is the in-cluster address,
``url`` the public one. A peer serves what it shares with the caller at ``GET /kaos/v1/shared``:
``{"owner": "<peer>", "datasets": [{name, description, location, latest, versions: [{tag, commit}]}]}``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

import requests

from .errors import AuthError, ConfigError, DatasetError, LakeFSError

PEERS_PATH, SHARED_PATH = "/kaos/v1/peers", "/kaos/v1/shared"
DATASET_PREFIX = "dataset-"
TIMEOUT = 30

_CACHE: dict = {}   # own lakeFS base URL -> Peers, once per process


@dataclass(frozen=True)
class Peer:
    """Another project of the organisation and the addresses of its lakeFS."""
    project: str
    endpoint: str = ""
    url: str = ""


@dataclass(frozen=True)
class Peers:
    """The own project and its peers, as the own lakeFS serves them."""
    project: str
    peers: tuple = ()


@dataclass
class PeerShares:
    """What one peer shares with the caller; ``note`` says why nothing could be listed ("" when it answered)."""
    peer: str
    datasets: list = field(default_factory=list)   # datasets.DatasetInfo with owner set
    note: str = ""


def clear_cache() -> None:
    _CACHE.clear()


def _too_old(base_url: str) -> ConfigError:
    return ConfigError(f"the lakeFS at {base_url} is too old for datasets shared between projects "
                       f"(it does not serve {PEERS_PATH}). Ask the platform team to update kaos-lake.")


def load(client) -> Peers:
    """The own project's peers (``GET /kaos/v1/peers`` with the client's own credential), cached per process."""
    if client.base_url in _CACHE:
        return _CACHE[client.base_url]
    resp = client.session.get(client.base_url + PEERS_PATH, timeout=TIMEOUT, allow_redirects=False)
    if resp.status_code in (301, 302, 303, 307, 308, 401):
        raise AuthError(f"lakeFS rejected the credential (peers of {client.base_url}). Run `kubecore login` again.")
    if resp.status_code == 403:
        raise AuthError(f"you are not allowed to list the peers of {client.base_url}.")
    if resp.status_code in (404, 405, 501):
        raise _too_old(client.base_url)
    if resp.status_code != 200:
        raise LakeFSError(f"listing peers failed: HTTP {resp.status_code} {(resp.text or '')[:300]}",
                          resp.status_code)
    try:
        body = resp.json()
    except ValueError:
        raise _too_old(client.base_url) from None   # an old lakeFS answers unknown paths with its web UI
    if not isinstance(body, dict) or not isinstance(body.get("peers", []), list):
        raise _too_old(client.base_url)
    found = Peers(str(body.get("project") or ""), tuple(
        Peer(str(p.get("project") or ""), str(p.get("endpoint") or ""), str(p.get("url") or ""))
        for p in body.get("peers") or [] if isinstance(p, dict) and p.get("project")))
    _CACHE[client.base_url] = found
    return found


def peer(client, owner: str) -> Peer:
    """The peer called ``owner``; DatasetError when it is not a project of the caller's organisation."""
    found = load(client)
    for p in found.peers:
        if p.project == owner:
            return p
    known = ", ".join(sorted(p.project for p in found.peers)) or "none"
    raise DatasetError(f"{owner} is not a project of your organisation that lakeFS knows "
                       f"(projects: {known}). Check the project name in <project>/dataset-<name>@<version>.")


def in_cluster(base_url: str) -> bool:
    """True when ``base_url`` is an in-cluster Service address (``*.svc`` or ``*.svc.cluster.local``)."""
    host = (urlsplit(base_url).hostname or "").lower()
    return host.endswith(".svc") or host.endswith(".svc.cluster.local")


def base_for(own_base_url: str, p: Peer) -> str:
    """The peer's lakeFS address seen from the caller: its endpoint in the cluster, else its public URL."""
    base = (p.endpoint or p.url) if in_cluster(own_base_url) else p.url
    if not base:
        raise DatasetError(f"project {p.project}'s lakeFS has no public URL, so it cannot be read from outside "
                           "the cluster. Read it from a pipeline step, or ask the platform team.")
    return base.rstrip("/")


def _shared_rows(owner: str, body) -> list:
    from .datasets import DatasetInfo
    rows = []
    for d in (body or {}).get("datasets") or []:
        name = str((d or {}).get("name") or "").rsplit("/", 1)[-1]
        if not name.startswith(DATASET_PREFIX):
            continue
        rows.append(DatasetInfo(repo=name, owner=owner, description=str(d.get("description") or ""),
                                location=str(d.get("location") or ""),
                                versions=[v["tag"] for v in d.get("versions") or [] if v.get("tag")]))
    return sorted(rows, key=lambda r: r.repo)


def _shares_of(client, p: Peer) -> PeerShares:
    peer_client = client.for_owner(p.project)
    try:
        resp = peer_client.session.get(peer_client.base_url + SHARED_PATH, timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException as exc:
        return PeerShares(p.project, note=f"cannot reach its lakeFS ({exc.__class__.__name__})")
    if resp.status_code == 401:
        return PeerShares(p.project)   # nothing shared with this project
    if resp.status_code == 404:
        return PeerShares(p.project, note="its lakeFS is too old to share datasets")
    if resp.status_code != 200:
        return PeerShares(p.project, note=f"its lakeFS answered HTTP {resp.status_code}")
    try:
        return PeerShares(p.project, _shared_rows(p.project, resp.json()))
    except (ValueError, AttributeError, TypeError, KeyError):
        return PeerShares(p.project, note="its lakeFS is too old to share datasets")


def shared(client) -> list:
    """For every peer, the datasets it shares with the caller (``PeerShares``), asked with the caller's token."""
    return [_shares_of(client, p) for p in sorted(load(client).peers, key=lambda x: x.project)]
