"""Checkpoint persistence helper for in-cluster steps (PRD-HPC-1461 D-76, Kubernetes backend).

Runs as two extra containers of a step pod, injected by `kubecore.resilience` (the step's own code is
never touched). Python standard library only; the CI ships this file once per app as the ConfigMap
`<app>-ckpt-helper`, mounted at /ckpt-helper and run as `python3 /ckpt-helper/checkpoint_helper.py <mode>`.

  restore  (init container)  put the newest VERIFIED copy of the step's checkpoint folder back before the
                             step starts, and expire copies of long-dead runs.
  watch    (sidecar)         copy the folder periodically (and when the pod is told to stop) as ONE tar
                             archive plus a sha256 manifest, keep at most KEEP copies, delete all of them
                             when the step succeeds.

Copies live in the app's lakeFS outputs repository, on their own branch that is never merged or
committed:  <branch>:<KEY>/ckpt-<utc time>-<id>.tar  and  .json  (the manifest, written LAST: a copy
without a manifest does not exist).

Contract: this helper NEVER fails the step. Every error is logged in plain words and swallowed; the
init container always exits 0 and the sidecar's exit code is ignored by Argo.
"""
import base64
import hashlib
import http.client
import json
import os
import secrets
import shutil
import ssl
import sys
import tarfile
import time
import urllib.parse

TAG = "[kaos-checkpoint]"
MANIFEST_VERSION = 1
MIN_EVERY = 60            # seconds: never copy more often than this
MAX_EVERY = 3600          # seconds: never wait longer than this between copies
OVERHEAD = 10             # a copy may take about 1/10 of the time between copies
SETTLE_SECONDS = 2        # a file modified more recently than this is still being written
SETTLE_MAX_WAIT = 10
SNAPSHOT_TRIES = 3
CHUNK = 1 << 20


def say(message):
    print("%s %s" % (TAG, message), file=sys.stderr, flush=True)


class Config:
    """Everything the helper reads from its environment (set by the enhancer)."""

    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.folder = env.get("KAOS_CHECKPOINT_DIR", "")
        self.endpoint = env.get("LAKEFS_ENDPOINT", "").rstrip("/")
        self.access = env.get("LAKEFS_ACCESS_KEY", "")
        self.secret = env.get("LAKEFS_SECRET_KEY", "")
        self.repo = env.get("CKPT_REPO", "")
        self.branch = env.get("CKPT_BRANCH", "kaos-checkpoints")
        self.source = env.get("CKPT_SOURCE_BRANCH", "main")
        self.key = env.get("CKPT_KEY", "").strip("/")
        self.root = env.get("CKPT_ROOT", "resume").strip("/")
        self.every = int(float(env.get("CKPT_EVERY_MIN", "10")) * 60)
        self.keep = int(env.get("CKPT_KEEP", "2"))
        self.expire_days = float(env.get("CKPT_EXPIRE_DAYS", "7"))
        self.grace = int(env.get("CKPT_GRACE_SECONDS", "30"))
        self.stage = env.get("CKPT_STAGE", "/stage")
        self.exit_file = env.get("CKPT_EXIT_FILE", "/var/run/argo/ctr/main/exitcode")
        self.poll = float(env.get("CKPT_POLL_SECONDS", "1"))

    def usable(self):
        return all([self.folder, self.endpoint, self.access, self.secret, self.repo, self.key])


class LakeFS:
    """The few lakeFS API calls the helper needs (basic auth with the app's key pair)."""

    def __init__(self, cfg):
        self.cfg = cfg
        url = urllib.parse.urlsplit(cfg.endpoint)
        self.https = url.scheme == "https"
        self.host = url.netloc
        self.base = url.path.rstrip("/") + "/api/v1"
        token = base64.b64encode(("%s:%s" % (cfg.access, cfg.secret)).encode()).decode()
        self.auth = "Basic " + token

    def _conn(self):
        if self.https:
            return http.client.HTTPSConnection(self.host, timeout=120, context=ssl.create_default_context())
        return http.client.HTTPConnection(self.host, timeout=120)

    def _url(self, sub, **query):
        suffix = "?" + urllib.parse.urlencode(query) if query else ""
        return "%s/repositories/%s%s%s" % (self.base, self.cfg.repo, sub, suffix)

    def call(self, method, sub, body=None, **query):
        """One small JSON request; returns (status, parsed JSON or None)."""
        conn = self._conn()
        try:
            headers = {"Authorization": self.auth}
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            conn.request(method, self._url(sub, **query), body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            try:
                return resp.status, (json.loads(raw) if raw else None)
            except ValueError:
                return resp.status, None
        finally:
            conn.close()

    def upload(self, name, file_path):
        """Stream a local file into the checkpoint branch as multipart/form-data (no size limit in memory)."""
        boundary = "kaosckpt" + secrets.token_hex(8)
        head = ('--%s\r\nContent-Disposition: form-data; name="content"; filename="blob"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n' % boundary).encode()
        tail = ("\r\n--%s--\r\n" % boundary).encode()
        size = os.path.getsize(file_path)
        conn = self._conn()
        try:
            conn.putrequest("POST", self._url("/branches/%s/objects" % self.cfg.branch, path=name))
            conn.putheader("Authorization", self.auth)
            conn.putheader("Content-Type", "multipart/form-data; boundary=%s" % boundary)
            conn.putheader("Content-Length", str(len(head) + size + len(tail)))
            conn.endheaders()
            conn.send(head)
            with open(file_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(CHUNK), b""):
                    conn.send(chunk)
            conn.send(tail)
            resp = conn.getresponse()
            resp.read()
            if resp.status not in (200, 201):
                raise RuntimeError("upload of %s answered HTTP %s" % (name, resp.status))
        finally:
            conn.close()

    def upload_bytes(self, name, data, stage):
        tmp = os.path.join(stage, "upload.tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
        try:
            self.upload(name, tmp)
        finally:
            os.unlink(tmp)

    def download(self, name, dest):
        conn = self._conn()
        try:
            conn.request("GET", self._url("/refs/%s/objects" % self.cfg.branch, path=name),
                         headers={"Authorization": self.auth})
            resp = conn.getresponse()
            if resp.status != 200:
                resp.read()
                raise RuntimeError("download of %s answered HTTP %s" % (name, resp.status))
            with open(dest, "wb") as fh:
                for chunk in iter(lambda: resp.read(CHUNK), b""):
                    fh.write(chunk)
        finally:
            conn.close()

    def read(self, name):
        tmp = os.path.join(self.cfg.stage, "read.tmp")
        self.download(name, tmp)
        try:
            with open(tmp, "rb") as fh:
                return fh.read()
        finally:
            os.unlink(tmp)

    def size(self, name):
        status, body = self.call("GET", "/refs/%s/objects/stat" % self.cfg.branch, path=name)
        return body.get("size_bytes") if status == 200 and body else None

    def delete(self, name):
        self.call("DELETE", "/branches/%s/objects" % self.cfg.branch, path=name)

    def listing(self, prefix):
        """Every object under prefix: [{path, size_bytes, mtime}], following pagination."""
        out, after = [], ""
        while True:
            status, body = self.call("GET", "/refs/%s/objects/ls" % self.cfg.branch,
                                     prefix=prefix, amount=1000, after=after)
            if status == 404:
                return out
            if status != 200 or not body:
                raise RuntimeError("listing %s answered HTTP %s" % (prefix, status))
            out += [o for o in body.get("results", []) if o.get("path_type", "object") == "object"]
            page = body.get("pagination") or {}
            if not page.get("has_more"):
                return out
            after = page.get("next_offset", "")

    def ensure_branch(self):
        """Make sure the checkpoint branch exists; False when the repository is not there."""
        status, _ = self.call("GET", "/branches/%s" % self.cfg.branch)
        if status == 200:
            return True
        if status == 404:
            status, _ = self.call("POST", "/branches", body={"name": self.cfg.branch, "source": self.cfg.source})
            return status in (200, 201, 409)
        return False


# ------------------------------------------------------------------------------------ the folder

def scan(folder):
    """[(relative path, size, mtime_ns)] of the regular files under folder, sorted."""
    found = []
    for base, _dirs, files in os.walk(folder):
        for name in files:
            full = os.path.join(base, name)
            if os.path.islink(full):
                continue
            st = os.stat(full)
            found.append((os.path.relpath(full, folder), st.st_size, st.st_mtime_ns))
    return sorted(found)


def settle(folder):
    """Wait (a few seconds at most) until no file was modified in the last SETTLE_SECONDS."""
    waited = 0
    while waited < SETTLE_MAX_WAIT:
        newest = max((m for _p, _s, m in scan(folder)), default=0)
        if time.time() - newest / 1e9 >= SETTLE_SECONDS:
            return
        time.sleep(1)
        waited += 1


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack(folder, archive):
    """Tar the folder into archive; returns the file list when it held no file changed while packing
    (retried a few times), the last list otherwise, and None when the folder is empty."""
    files = None
    for _ in range(SNAPSHOT_TRIES):
        settle(folder)
        files = scan(folder)
        if not files:
            return None
        with tarfile.open(archive, "w") as tar:
            for rel, _size, _mtime in files:
                tar.add(os.path.join(folder, rel), arcname=rel, recursive=False)
        if scan(folder) == files:
            return files
        say("files kept changing while packing the checkpoint folder; trying again")
    return files


def unpack(archive, folder):
    """Extract a verified archive into folder: regular files only, nothing outside folder."""
    with tarfile.open(archive, "r") as tar:
        members = []
        for m in tar.getmembers():
            target = os.path.realpath(os.path.join(folder, m.name))
            if not m.isfile() or not target.startswith(os.path.realpath(folder) + os.sep):
                raise RuntimeError("the archive holds an entry it should not: %s" % m.name)
            members.append(m)
        tar.extractall(folder, members=members)
    for base, dirs, files in os.walk(folder):
        for name in dirs:
            os.chmod(os.path.join(base, name), 0o777)   # the step may run as any user
        for name in files:
            os.chmod(os.path.join(base, name), 0o666)


# ------------------------------------------------------------------------------------ copies

def copies(api):
    """Manifests of the copies of this step, newest first: [(manifest object name, manifest dict)]."""
    prefix = "%s/%s/" % (api.cfg.root, api.cfg.key)
    names = sorted((o["path"] for o in api.listing(prefix) if o["path"].endswith(".json")), reverse=True)
    out = []
    for name in names:
        try:
            out.append((name, json.loads(api.read(name))))
        except Exception as exc:   # an unreadable manifest is not a copy
            say("ignoring an unreadable checkpoint manifest (%s)" % exc)
    return out


def restore(api):
    """Restore the newest verified copy into the folder. Returns True when one was restored."""
    cfg = api.cfg
    for name, manifest in copies(api):
        archive = os.path.join(cfg.stage, "restore.tar")
        try:
            api.download("%s/%s/%s" % (cfg.root, cfg.key, manifest["archive"]), archive)
            if os.path.getsize(archive) != manifest["size"] or sha256_of(archive) != manifest["sha256"]:
                raise RuntimeError("the copy does not match its checksum")
            unpack(archive, cfg.folder)
            say("continuing from the checkpoint saved at %s (%d files)"
                % (time.strftime("%H:%M:%S UTC", time.gmtime(manifest["created"])), manifest["files"]))
            return True
        except Exception as exc:
            say("skipping checkpoint %s: %s" % (name.rsplit("/", 1)[-1], exc))
        finally:
            if os.path.exists(archive):
                os.unlink(archive)
    return False


def prune(api, keep):
    """Keep the newest `keep` copies; remove older ones and archives that never got a manifest."""
    prefix = "%s/%s/" % (api.cfg.root, api.cfg.key)
    objects = [o["path"] for o in api.listing(prefix)]
    manifests = sorted((p for p in objects if p.endswith(".json")), reverse=True)
    wanted = set()
    for name in manifests[:keep]:
        wanted.update([name, name[:-5] + ".tar"])
    for path in objects:
        if path not in wanted:
            api.delete(path)


def delete_all(api):
    prefix = "%s/%s/" % (api.cfg.root, api.cfg.key)
    for obj in api.listing(prefix):
        api.delete(obj["path"])


def expire(api):
    """Remove copies of runs that never finished and are older than the retention."""
    limit = time.time() - api.cfg.expire_days * 86400
    for obj in api.listing(api.cfg.root + "/"):
        if obj.get("mtime", time.time()) < limit:
            api.delete(obj["path"])


def copy_once(api, last_signature):
    """Save one copy. Returns (seconds it took, signature of what was saved or last_signature)."""
    cfg, started = api.cfg, time.time()
    archive = os.path.join(cfg.stage, "copy.tar")
    try:
        if not os.path.isdir(cfg.folder) or scan(cfg.folder) == last_signature:
            return 0, last_signature     # nothing new since the last copy
        files = pack(cfg.folder, archive)
        if not files:
            return 0, last_signature
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(2)
        base = "%s/%s/ckpt-%s" % (cfg.root, cfg.key, stamp)
        api.upload(base + ".tar", archive)
        size = os.path.getsize(archive)
        if api.size(base + ".tar") != size:
            raise RuntimeError("the uploaded archive has the wrong size")
        manifest = {"version": MANIFEST_VERSION, "archive": "ckpt-%s.tar" % stamp, "sha256": sha256_of(archive),
                    "size": size, "files": len(files), "created": int(time.time())}
        api.upload_bytes(base + ".json", json.dumps(manifest).encode(), cfg.stage)   # last: it completes the copy
        prune(api, cfg.keep)
        took = time.time() - started
        say("saved a checkpoint copy: %d files, %.1f MB, %.0f s" % (len(files), size / 1e6, took))
        return took, files
    except Exception as exc:
        say("could not save a checkpoint copy (%s); the step is not affected" % exc)
        return time.time() - started, last_signature
    finally:
        if os.path.exists(archive):
            os.unlink(archive)


# ------------------------------------------------------------------------------------ the two modes

def step_exit_code(cfg):
    """The step's exit code once it has ended (Argo writes it to a shared file), else None."""
    try:
        with open(cfg.exit_file) as fh:
            text = fh.read().strip()
        return int(text) if text else None
    except (OSError, ValueError):
        return None


def run_restore(cfg):
    api = LakeFS(cfg)
    os.makedirs(cfg.folder, exist_ok=True)
    try:
        if not api.ensure_branch():
            say("the outputs repository is not available; the step starts without a saved checkpoint")
            return
        if os.listdir(cfg.folder):
            say("the checkpoint folder is not empty; nothing restored")
        elif not restore(api):
            say("no saved checkpoint for this step: starting from the beginning")
        expire(api)
    except Exception as exc:
        say("could not look for a saved checkpoint (%s); the step starts without one" % exc)


def run_watch(cfg):
    api = LakeFS(cfg)
    stopping = []
    import signal
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.append(time.time()))
    try:
        if not api.ensure_branch():
            say("the outputs repository is not available; no checkpoint copies will be saved")
            return
    except Exception as exc:
        say("checkpoint copies are off (%s)" % exc)
        return
    interval, signature = cfg.every, None
    next_at = time.time() + interval
    while True:
        code = step_exit_code(cfg)
        if code is not None:
            return finish(api, code)
        if stopping:
            return on_stop(api, stopping[0], signature)
        if time.time() >= next_at:
            took, signature = copy_once(api, signature)
            # a copy should take about a tenth of the time between copies
            interval = min(MAX_EVERY, max(cfg.every, int(took * OVERHEAD), MIN_EVERY))
            next_at = time.time() + interval
        time.sleep(cfg.poll)


def finish(api, code):
    """The step has ended: success removes every copy, anything else keeps them."""
    try:
        if code == 0:
            delete_all(api)
            say("step finished; its checkpoint copies were removed")
        else:
            say("step ended with exit code %d; its checkpoint copies are kept" % code)
    except Exception as exc:
        say("could not remove the checkpoint copies (%s); they expire by themselves" % exc)


def on_stop(api, stopped_at, signature):
    """The pod is being stopped (node loss, preemption): save at once, again if the step saves and ends."""
    cfg = api.cfg
    code = step_exit_code(cfg)
    if code is not None:       # Argo stopping the sidecar after the step ended
        return finish(api, code)
    deadline = stopped_at + cfg.grace - 3
    took, signature = copy_once(api, signature)
    while time.time() < deadline and step_exit_code(cfg) is None:
        time.sleep(cfg.poll)
    code = step_exit_code(cfg)
    if code == 0:
        return finish(api, code)
    if code is not None and deadline - time.time() > took * 1.5:
        copy_once(api, signature)    # the step saved its own checkpoint on the stop signal


def main(argv):
    cfg = Config()
    mode = argv[1] if len(argv) > 1 else ""
    if mode not in ("restore", "watch"):
        say("usage: restore | watch")
        return 0
    if not cfg.usable():
        say("checkpoint copies are off: the lakeFS settings are incomplete")
        return 0
    os.makedirs(cfg.stage, exist_ok=True)
    try:
        run_restore(cfg) if mode == "restore" else run_watch(cfg)
    except Exception as exc:     # never fail the step
        say("unexpected problem (%s); the step is not affected" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
