"""Image pre-staging: a MeluXina job that queues longer than the registry token's hour must not
fail its image pull (live 2026-11-05: three GPU jobs queued ~70 min, `apptainer pull` then failed
"invalid username/password", exit 231, and the waiter resubmitted into another full queue wait).

At submit, while the token is fresh, the waiter streams the image layers to the login-node stager
as a docker-archive tarball; the job builds its SIF from it with no registry access.

Covered here: the stdlib registry client against a real local HTTP registry (token flow, manifest
list -> linux/amd64, blob redirect without the registry's Authorization), the streamed tar and its
trailer, the stager exchange (skip when staged, space refusal, fallbacks that never block the
submit), and the job script's branch order in bash with a fake apptainer.
Run:  python -m pytest tests/ -v
"""
import ast
import base64
import hashlib
import http.server
import io
import json
import os
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kubecore.meluxina import MELUXINA_SUBMIT_CODE  # noqa: E402

GZ = "application/vnd.oci.image.layer.v1.tar+gzip"


def sha(b):
    return "sha256:" + hashlib.sha256(b).hexdigest()


class FakeRegistry:
    """A registry on 127.0.0.1: bearer token flow (Basic oauth2accesstoken:<tok> -> token),
    an index with an attestation, an arm64 and an amd64 image, blobs served by redirect."""

    def __init__(self, token_required=True):
        self.layers = [os.urandom(1500), os.urandom(700_000) + b"x", b"\x1f\x8b" + os.urandom(37)]
        self.config = json.dumps({"architecture": "amd64", "os": "linux"}).encode()
        self.manifest = json.dumps({
            "schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"mediaType": "application/vnd.oci.image.config.v1+json",
                       "digest": sha(self.config), "size": len(self.config)},
            "layers": [{"mediaType": GZ, "digest": sha(b), "size": len(b)} for b in self.layers]}).encode()
        arm = json.dumps({"schemaVersion": 2, "config": {"digest": sha(b"arm"), "size": 3},
                          "layers": [{"digest": sha(b"arm"), "size": 3}]}).encode()
        self.arm = arm
        self.index = json.dumps({"schemaVersion": 2, "manifests": [
            {"digest": sha(b"att"), "platform": {"os": "unknown", "architecture": "unknown"}},
            {"digest": sha(arm), "platform": {"os": "linux", "architecture": "arm64"}},
            {"digest": sha(self.manifest), "platform": {"os": "linux", "architecture": "amd64"}}]}).encode()
        self.blobs = {sha(b): b for b in self.layers + [self.config]}
        self.manifests = {sha(self.manifest): self.manifest, sha(arm): arm, "v1": self.index,
                          sha(self.index): self.index}
        self.token_required, self.log, self.leaked = token_required, [], []
        reg = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b"", headers=None):
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                reg.log.append((self.path, self.headers.get("Authorization")))
                if self.path.startswith("/token"):
                    want = "Basic " + base64.b64encode(b"oauth2accesstoken:gcp-tok").decode()
                    if self.headers.get("Authorization") != want:
                        return self._send(401)
                    return self._send(200, json.dumps({"token": "reg-bearer"}).encode())
                if self.path.startswith("/store/"):      # blob store behind a redirect
                    if self.headers.get("Authorization"):
                        reg.leaked.append(self.path)
                    return self._send(200, reg.blobs["sha256:" + self.path.split("/")[-1]])
                if reg.token_required and self.headers.get("Authorization") != "Bearer reg-bearer":
                    return self._send(401, headers={"WWW-Authenticate": 'Bearer realm="http://%s/token",'
                                                    'service="reg",scope="repository:p/app:pull"' % reg.host})
                kind, _, ref = self.path.split("/v2/p/app/")[1].partition("/")
                if kind == "manifests" and ref in reg.manifests:
                    return self._send(200, reg.manifests[ref])
                if kind == "blobs" and ref in reg.blobs:
                    return self._send(307, headers={"Location": "http://localhost:%d/store/%s" % (reg.httpd.server_port, ref.split(":")[1])})
                self._send(404)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.host = "127.0.0.1:%d" % self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _code():
    for k, v in {"SLURM_TOKEN": "t", "WF_UID": "u", "STEP_NAME": "s", "IMAGE_REF": "r/x:t",
                 "HPC_USER": "u1", "HPC_ACCOUNT": "p1", "HPC_SCRATCH": "/s", "HPC_HOME": "/h"}.items():
        os.environ.setdefault(k, v)
    g = {}
    exec(MELUXINA_SUBMIT_CODE.split("jid = None")[0], g)
    return g


def _token_host(g):
    # The test registry stands in for a GAR host: it gets the GCP token.
    g["registry_token_host"] = lambda host: True


def _read_tar(chunks):
    data = b"".join(chunks)
    assert data[-65:-1].decode() == hashlib.sha256(data[:-65]).hexdigest(), "trailer = sha256 of the tar"
    return data[:-65], tarfile.open(fileobj=io.BytesIO(data[:-65]))


def test_streams_a_multi_layer_image_from_the_amd64_manifest_with_the_token():
    reg = FakeRegistry()
    try:
        g = _code()
        _token_host(g)
        registry = g["Registry"](reg.host, "gcp-tok")
        host, repo, ref = g["parse_image"]("%s/p/app@%s" % (reg.host, sha(reg.manifest)))
        assert (host, repo, ref) == (reg.host, "p/app", sha(reg.manifest))
        # a tag resolves through the index to the linux/amd64 image, not arm64 or the attestation
        m = g["image_manifest"](registry, "p/app", "v1")
        assert [d["digest"] for d in m["layers"]] == [sha(b) for b in reg.layers]
        entries, total = g["image_plan"](registry, "p/app", m)
        raw, tar = _read_tar(g["image_feed"](registry, "p/app", entries, 1e18))
        assert len(raw) + 65 == total + 65 and total == len(raw), "declared size = streamed size"
        names = tar.getnames()
        assert names[0] == "manifest.json" and len(names) == 5
        manifest = json.load(tar.extractfile("manifest.json"))[0]
        assert manifest["Config"] == sha(reg.config)[7:] + ".json"
        for name, blob in zip(manifest["Layers"], reg.layers):
            assert name == sha(blob)[7:] + ".tar.gz"
            assert tar.extractfile(name).read() == blob, "layers are copied as they are"
        # auth: bearer from the token endpoint with Basic oauth2accesstoken:<gcp token>
        assert any(p.startswith("/token") for p, _ in reg.log)
        assert all(a == "Bearer reg-bearer" for p, a in reg.log if "/v2/" in p and a)
        assert reg.leaked == [], "the registry's Authorization never reaches the blob store"
    finally:
        reg.close()


def test_a_corrupt_layer_is_not_completed():
    reg = FakeRegistry()
    try:
        g = _code()
        _token_host(g)
        registry = g["Registry"](reg.host, "gcp-tok")
        m = g["image_manifest"](registry, "p/app", sha(reg.manifest))
        entries, _ = g["image_plan"](registry, "p/app", m)
        reg.blobs[sha(reg.layers[1])] = b"y" * len(reg.layers[1])        # bytes no longer match the digest
        sent = []
        try:
            for c in g["image_feed"](registry, "p/app", entries, 1e18):
                sent.append(c)
        except ValueError as e:
            assert "mismatch" in str(e)
        else:
            raise AssertionError("a layer that does not match its digest must abort the stream")
        assert not sent or len(sent[-1]) != 65, "no trailer after a bad layer"
    finally:
        reg.close()


def test_the_anonymous_registry_gets_no_token():
    reg = FakeRegistry(token_required=False)
    try:
        g = _code()
        registry = g["Registry"](reg.host, "gcp-tok")        # not a GAR host: token withheld
        assert g["image_manifest"](registry, "p/app", sha(reg.manifest))["layers"]
        assert all(a is None for _, a in reg.log)
    finally:
        reg.close()


# ---------------------------------------------------------------- the stager exchange

class FakeStager:
    def __init__(self, status=None, image_rc=0, status_rc=0):
        self.status, self.image_rc, self.status_rc, self.calls, self.received = status, image_rc, status_rc, [], b""

    def __call__(self, words, feed=None):
        self.calls.append(words)
        if words[0] == "image-status":
            ev = [dict(self.status, event="image_status")] if self.status is not None else []
            return self.status_rc, ev
        self.received = b"".join(feed)
        return self.image_rc, ([{"event": "done", "path": "/scr/kaos/p/images/k.tar"}] if self.image_rc == 0 else [])


def _stage(monkeypatch, tmp_path, stager, reg, key=True):
    g = _code()
    _token_host(g)
    if key:
        (tmp_path / "id_ed25519").write_text("k")
    g.update(STAGING_DIR=str(tmp_path), stager=stager)
    monkeypatch.setattr(g["subprocess"], "call", lambda *a, **kw: 0)
    img = "%s/p/app@%s" % (reg.host, sha(reg.manifest))
    return g, img


def test_stages_the_tar_under_the_jobs_cache_key(monkeypatch, tmp_path):
    reg = FakeRegistry()
    try:
        stager = FakeStager(status={"ready": False})
        g, img = _stage(monkeypatch, tmp_path, stager, reg)
        assert g["stage_image"](img, "gcp-tok") == "/scr/kaos/p/images/k.tar"
        key = hashlib.sha256(img.encode()).hexdigest()[:16]           # the job's: sha256sum | cut -c1-16
        assert stager.calls[0] == ["image-status", "--key", key]
        words = stager.calls[1]
        assert words[:3] == ["image", "--key", key] and words[3] == "--size"
        assert words[4] == len(stager.received) - 65
        assert tarfile.open(fileobj=io.BytesIO(stager.received[:-65])).getnames()[0] == "manifest.json"
    finally:
        reg.close()


def test_an_image_already_staged_is_not_fetched_again(monkeypatch, tmp_path):
    reg = FakeRegistry()
    try:
        stager = FakeStager(status={"ready": True, "path": "/scr/kaos/p/images/k.tar"})
        g, img = _stage(monkeypatch, tmp_path, stager, reg)
        assert g["stage_image"](img, "gcp-tok") == "/scr/kaos/p/images/k.tar"
        assert [w[0] for w in stager.calls] == ["image-status"] and reg.log == []
    finally:
        reg.close()


def test_without_the_key_an_old_stager_or_no_space_the_job_pulls(monkeypatch, tmp_path):
    reg = FakeRegistry()
    try:
        g, img = _stage(monkeypatch, tmp_path, FakeStager(status={"ready": False}), reg, key=False)
        assert g["stage_image"](img, "gcp-tok") == "" and reg.log == []
        old = FakeStager(status=None, status_rc=2)                     # unknown subcommand: no image event
        g, img = _stage(monkeypatch, tmp_path, old, reg)
        assert g["stage_image"](img, "gcp-tok") == "" and reg.log == []
        full = FakeStager(status={"ready": False}, image_rc=76)         # NoSpace
        g, img = _stage(monkeypatch, tmp_path, full, reg)
        assert g["stage_image"](img, "gcp-tok") == ""
        assert [w[0] for w in full.calls] == ["image-status", "image"], "no pointless retry on no space"
    finally:
        reg.close()


def test_a_registry_failure_never_raises_and_a_dropped_stream_retries_once(monkeypatch, tmp_path):
    reg = FakeRegistry()
    try:
        stager = FakeStager(status={"ready": False}, image_rc=75)
        g, img = _stage(monkeypatch, tmp_path, stager, reg)
        assert g["stage_image"](img, "gcp-tok") == ""
        assert [w[0] for w in stager.calls] == ["image-status", "image", "image"]
        bad = "%s/p/missing@%s" % (reg.host, sha(reg.manifest))
        assert g["stage_image"](bad, "gcp-tok") == "", "a 404 from the registry is a fallback, not an error"
        assert g["stage_image"]("docker-hub-name", "t") == ""
    finally:
        reg.close()


def test_the_stager_call_passes_tar_bytes_through_ssh_unchanged(monkeypatch, tmp_path):
    out = tmp_path / "received"
    ssh = tmp_path / "bin" / "ssh"
    ssh.parent.mkdir()
    ssh.write_text("#!/bin/sh\ncat > %s\necho '{\"event\": \"done\", \"path\": \"/p\"}'\n" % out)
    ssh.chmod(0o755)
    for k, v in {"HPC_USER": "u1", "HPC_ACCOUNT": "p1", "HPC_SCRATCH": "/s", "HPC_HOME": "/h"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PATH", str(ssh.parent) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("IMAGE_REF", "r/x:t")
    g = _code()
    payload = bytes(range(256)) * 5000
    rc, ev = g["stager"](["image", "--key", "k", "--size", len(payload)],
                         iter([payload[:1000], payload[1000:], b"%s\n" % b"ab"]))
    assert rc == 0 and ev[-1]["event"] == "done"
    assert out.read_bytes() == payload + b"ab\n"


# ---------------------------------------------------------------- the job script

def _job_lines():
    fn = next(n for n in ast.walk(ast.parse(MELUXINA_SUBMIT_CODE))
              if isinstance(n, ast.FunctionDef) and n.name == "submit")
    batch = next(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "batch")
    return [e.value for e in batch.value.args[0].elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def _run_job(tmp_path, staged, build_ok=True, pull_ok=True, preexisting_sif=False):
    lines = _job_lines()
    start = lines.index('if [ ! -f "$SIF" ]; then')
    end = lines.index("fi", start)
    scr = tmp_path / "scratch"
    (scr / "sif-cache").mkdir(parents=True)
    tar = scr / "kaos" / "p" / "images" / "k.tar"
    tar.parent.mkdir(parents=True)
    if staged:
        tar.write_bytes(b"tar")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "apptainer").write_text(
        '#!/bin/bash\necho "$1 $3" >> "$SCR/calls"\n'
        'if [ "$1" = build ]; then [ "%d" = 1 ] || { printf half > "$2"; exit 1; }; fi\n'
        'if [ "$1" = pull ]; then [ "%d" = 1 ] || exit 1; fi\n'
        'printf sif > "$2"\n' % (build_ok, pull_ok))
    (bindir / "apptainer").chmod(0o755)
    sif = scr / "sif-cache" / "abc.sif"
    if preexisting_sif:
        sif.write_text("cached")
    script = "\n".join(['fail(){ echo "$1" > "$SCR/failed"; exit "$1"; }'] + lines[start:end + 1])
    env = dict(os.environ, SCR=str(scr), SIF=str(sif), IMAGE_REF="europe-docker.pkg.dev/p/app@sha256:ab",
               SLURM_JOB_ID="1", REG_TOKEN="expired", PATH=str(bindir) + os.pathsep + os.environ["PATH"])
    if staged is not None:
        env["IMAGE_STAGED"] = str(tar)
    rc = subprocess.run(["bash", "-c", script], env=env, stdout=subprocess.PIPE).returncode
    calls = (scr / "calls").read_text().splitlines() if (scr / "calls").exists() else []
    return rc, calls, scr, sif, tar


def test_job_builds_from_the_staged_layers_and_never_touches_the_registry(tmp_path):
    rc, calls, scr, sif, tar = _run_job(tmp_path, staged=True)
    assert rc == 0 and calls == ["build docker-archive://%s" % tar]
    assert sif.read_text() == "sif"
    assert sorted(p.name for p in sif.parent.iterdir()) == ["abc.sif"], "part-file renamed away"


def test_job_pulls_when_nothing_is_staged(tmp_path):
    rc, calls, *_ = _run_job(tmp_path, staged=None)
    assert rc == 0 and [c.split()[0] for c in calls] == ["pull"]
    rc, calls, *_ = _run_job(tmp_path / "b", staged=False)       # path given, file missing
    assert rc == 0 and [c.split()[0] for c in calls] == ["pull"]


def test_job_falls_back_to_the_pull_when_the_build_fails_and_leaves_no_part_file(tmp_path):
    rc, calls, scr, sif, _ = _run_job(tmp_path, staged=True, build_ok=False)
    assert rc == 0 and [c.split()[0] for c in calls] == ["build", "pull"]
    assert sorted(p.name for p in sif.parent.iterdir()) == ["abc.sif"]
    rc, calls, scr, sif, _ = _run_job(tmp_path / "b", staged=True, build_ok=False, pull_ok=False)
    assert rc == 231 and list(sif.parent.iterdir()) == []


def test_a_cached_sif_needs_neither(tmp_path):
    rc, calls, *_ = _run_job(tmp_path, staged=True, preexisting_sif=True)
    assert rc == 0 and calls == []


def test_staged_tars_are_cleaned_up_and_the_env_reaches_the_job():
    lines = _job_lines()
    assert any(l.startswith('[ -n "$IMAGE_STAGED" ] && find') and '-name "*.tar"' in l and '-mtime +2' in l
               for l in lines)
    assert "'IMAGE_STAGED=' + IMAGE_STAGED" in MELUXINA_SUBMIT_CODE
