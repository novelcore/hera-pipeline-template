"""PRD-1016 — the MeluXina HPC leg the `platform.kubecore.io/hpc` annotation reserved.

`enhance_hpc` runs as the last enhancement pass. Active only when the pipeline
context carries `hpc.enabled` (Derive idiom: the operator sets it iff the
parent KubePool is HPC-ready, so non-HPC pools render byte-identically).

What it does (F-02/F-03/F-06):
  * re-emits the `target` submit-form parameter (gcp | <provider>);
  * every GPU step WITHOUT an existing task `when` (quantization-gated steps
    keep in-cluster-only behaviour this slice) gains a `-meluxina` twin DAG
    task with complementary `when:` clauses on `target`;
  * downstream `depends` tokens that reference a routed step are rewritten to
    gate on the Succeeded||Skipped twin pair (exactly one twin runs);
  * one `meluxina-run` CONTAINER template is appended (the release gate
    rejects script templates): an idempotent Slurm REST submit keyed on
    workflow.uid — a retried pod ADOPTS the queued/running job instead of
    double-submitting a full-node run — then a poll to terminal state,
    emitting `slurm-job-id` as an output.

Operational notes baked in from the live F-01/F-02 shakedown (2026-08):
  * the rotating Slurm JWT arrives via the `meluxina-jwt` Secret (PRD-1016
    F-07 ExternalSecret in the ml namespace, 5m refresh);
  * the batch script restores the Lmod init (`bash -l` + explicit source) —
    Slurm's mandatory `environment` field wipes it;
  * images pull through a digest-keyed Lustre SIF cache (D-02: cold ~8 min,
    warm ~7 s, measured on mel2107); registry auth is a best-effort
    metadata-server access token (GAR);
  * data plane (F-04/F-08): the submit pod mints a short-lived Zitadel
    bearer from the mounted machine key (the same JWT-profile recipe as the
    seeded mlflow_zitadel_auth module) and passes it in the Slurm job
    environment together with the PUBLIC MLflow/lakeFS endpoints — never the
    machine key itself (T-03: no long-lived credential leaves the cluster).
    The batch script stages the pinned dataset version from the lakeFS
    public endpoint to a Lustre cache keyed by lakeFS commit (D-04: the
    in-cluster manifest-only/S3-gateway streaming path is blocked by the
    SSO front off-cluster) and bind-mounts it read-only at
    /kubecore/dataset (KUBECORE_DATASET_DIR) for the step.
"""

import json
import re

from kubecore.kaos_lib_support import ENV as KAOS_LIB_SUPPORT_ENV
from kubecore.kaos_lib_support import support_value
from kubecore.outputs_repo import OUTPUTS_REF, checkpoint_prefix, outputs_repo

# The submit/poll program the meluxina-run container executes via
# `python3 -c`. Plain string — no Argo tags inside (all run-time inputs
# arrive via env), so it survives every templating layer verbatim.
MELUXINA_SUBMIT_CODE = r'''
STAGEOUT = r"""
# F-05 stage-out: the step's declared outputs (/work/output/<name>.json,
# what Argo would have read as outputs.parameters in-cluster) go to lakeFS
# at hpc-outputs/{wf-uid}/{step}/ on a hand-off branch of the app's outputs
# repository (outputs-<app>); the waiter fetches them back into the twin's outputs so
# downstream steps see real values, then deletes the branch. They never touch `main`:
# lakeFS refuses a merge into a branch with uncommitted objects, and the step's real
# results (checkpoints) are written by the step itself, inside the image, with the
# kubecore package's run writer (branch run-<run>-<kind>, merged into main).
import json, os, pathlib, urllib.error, urllib.parse, urllib.request
base = os.environ['LAKEFS_ENDPOINT'].rstrip('/') + '/api/v1'
H = {'Authorization': 'Bearer ' + os.environ['LAKEFS_BEARER_TOKEN']}
repo = os.environ['OUTPUTS_REPO']
branch = 'hpc-%s-%s' % (os.environ['WF_UID'], os.environ['STEP_NAME'])
try:
    urllib.request.urlopen(urllib.request.Request(
        base + '/repositories/%s/branches' % repo, method='POST',
        data=json.dumps({'name': branch, 'source': os.environ.get('OUTPUTS_REF') or 'main'}).encode(),
        headers=dict(H, **{'Content-Type': 'application/json'})), timeout=60).read()
except urllib.error.HTTPError as e:
    if e.code != 409:   # 409: a retry of this stage-out created it already
        raise
prefix = 'hpc-outputs/%s/%s/' % (os.environ['WF_UID'], os.environ['STEP_NAME'])
out = pathlib.Path(os.environ['KAOS_WORK']) / 'output'
for name in [n for n in os.environ.get('STEP_OUTPUTS', '').split(',') if n]:
    f = out / (name + '.json')
    if not f.exists():
        print('stage-out: no', f, flush=True); continue
    data = f.read_bytes()
    body = (b'--B\r\nContent-Disposition: form-data; name="content"; filename="f"\r\n'
            b'Content-Type: application/octet-stream\r\n\r\n' + data + b'\r\n--B--\r\n')
    q = urllib.parse.urlencode({'path': prefix + name + '.json'})
    req = urllib.request.Request(base + '/repositories/%s/branches/%s/objects?%s' % (repo, branch, q),
                                 data=body, method='POST',
                                 headers=dict(H, **{'Content-Type': 'multipart/form-data; boundary=B'}))
    urllib.request.urlopen(req, timeout=120).read()
    print('stage-out:', name, len(data), 'bytes ->', prefix, flush=True)
"""
CKPTOUT = r"""
# Checkpoint stage-out (PRD-HPC-1461 D-44 as amended 2026-11-05, T-19): a resumable step saved
# <work>/output/checkpoint/ with kaos_lib.checkpoint and exited 85. Before the job ends, upload
# it to the app's outputs repository on the branch hpc-ckpt-<wf-uid>-<step> (kept, so the
# checkpoint stays in lineage) at hpc-checkpoints/<wf-uid>/<step>/attempt-<n>/, check every
# file's size, commit, and write the commit id to $KAOS_CKPT_FILE. Files are streamed, never
# held in memory. Any failure exits non-zero: no commit id, no continuation.
import http.client, json, os, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
ep = urllib.parse.urlsplit(os.environ['LAKEFS_ENDPOINT'].rstrip('/'))
base = os.environ['LAKEFS_ENDPOINT'].rstrip('/') + '/api/v1'
H = {'Authorization': 'Bearer ' + os.environ['LAKEFS_BEARER_TOKEN']}
repo = os.environ['OUTPUTS_REPO']
wf, step, attempt = os.environ['WF_UID'], os.environ['STEP_NAME'], os.environ.get('KAOS_ATTEMPT') or '1'
branch = 'hpc-ckpt-%s-%s' % (wf, step)
prefix = 'hpc-checkpoints/%s/%s/attempt-%s/' % (wf, step, attempt)
src = pathlib.Path(os.environ['KAOS_WORK']) / 'output' / 'checkpoint'
files = sorted(f for f in src.rglob('*') if f.is_file()) if src.is_dir() else []
if not files:
    print('checkpoint stage-out: nothing in', src, flush=True); sys.exit(1)
def call(method, path, body=None, ok=(200, 201)):
    req = urllib.request.Request(base + path, method=method, headers=dict(H, **{'Content-Type': 'application/json'}),
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, {}
code, _ = call('POST', '/repositories/%s/branches' % repo, {'name': branch, 'source': os.environ.get('OUTPUTS_REF') or 'main'})
if code not in (200, 201, 409):   # 409: an earlier attempt created it
    print('checkpoint stage-out: cannot create', branch, code, flush=True); sys.exit(1)
def upload(f, path):
    size = f.stat().st_size
    pre = ('--B\r\nContent-Disposition: form-data; name="content"; filename="f"\r\n'
           'Content-Type: application/octet-stream\r\n\r\n').encode()
    post = b'\r\n--B--\r\n'
    q = urllib.parse.urlencode({'path': path})
    conn = (http.client.HTTPSConnection if ep.scheme == 'https' else http.client.HTTPConnection)(ep.netloc, timeout=600)
    conn.putrequest('POST', ep.path + '/api/v1/repositories/%s/branches/%s/objects?%s' % (repo, branch, q))
    for k, v in dict(H, **{'Content-Type': 'multipart/form-data; boundary=B',
                          'Content-Length': str(len(pre) + size + len(post))}).items():
        conn.putheader(k, v)
    conn.endheaders()
    conn.send(pre)
    with open(f, 'rb') as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            conn.send(chunk)
    conn.send(post)
    status = conn.getresponse().status
    conn.close()
    if status not in (200, 201):
        raise IOError('upload %s: HTTP %d' % (path, status))
    code, st = call('GET', '/repositories/%s/refs/%s/objects/stat?%s' % (repo, branch, q))
    if code != 200 or st.get('size_bytes') != size:
        raise IOError('upload %s: stored size %s, local %d' % (path, st.get('size_bytes'), size))
total = 0
for f in files:
    path = prefix + f.relative_to(src).as_posix()
    for n in range(4):
        try:
            upload(f, path)
            break
        except Exception as e:
            if n == 3:
                print('checkpoint stage-out:', e, flush=True); sys.exit(1)
            time.sleep(5 * (n + 1))
    total += f.stat().st_size
code, c = call('POST', '/repositories/%s/branches/%s/commits' % (repo, branch),
               {'message': 'checkpoint: %s attempt %s' % (step, attempt),
                'metadata': {'kaos.kind': 'checkpoint', 'workflow_uid': wf, 'step': step, 'attempt': str(attempt)}})
if code not in (200, 201) or not c.get('id'):
    print('checkpoint stage-out: commit failed', code, flush=True); sys.exit(1)
open(os.environ['KAOS_CKPT_FILE'], 'w').write(c['id'] + ' ' + prefix)
print('checkpoint stage-out: %d files, %d bytes -> %s@%s %s' % (len(files), total, branch, c['id'][:12], prefix), flush=True)
"""

CKPTIN = r"""
# Checkpoint stage-in for a continued job: download hpc-checkpoints/.../attempt-<n>/ at the commit the
# previous attempt staged out ($KAOS_RESUME_REF, $KAOS_RESUME_PREFIX) into <work>/resume, each file to a
# part-file renamed when complete and checked against its size. Exits non-zero if anything is
# missing: a continuation never silently starts from scratch.
import json, os, pathlib, sys, urllib.parse, urllib.request
base = os.environ['LAKEFS_ENDPOINT'].rstrip('/') + '/api/v1'
H = {'Authorization': 'Bearer ' + os.environ['LAKEFS_BEARER_TOKEN']}
repo, ref, prefix = os.environ['OUTPUTS_REPO'], os.environ['KAOS_RESUME_REF'], os.environ['KAOS_RESUME_PREFIX']
dest = pathlib.Path(os.environ['KAOS_WORK']) / 'resume'
def get(path):
    return urllib.request.urlopen(urllib.request.Request(base + path, headers=H), timeout=600)
objs, after = [], ''
while True:
    q = urllib.parse.urlencode({'prefix': prefix, 'after': after, 'amount': 1000})
    page = json.load(get('/repositories/%s/refs/%s/objects/ls?%s' % (repo, ref, q)))
    objs += [o for o in page.get('results', []) if o.get('path_type', 'object') == 'object']
    if not page.get('pagination', {}).get('has_more'):
        break
    after = page['pagination']['next_offset']
if not objs:
    print('checkpoint stage-in: nothing at', ref, prefix, flush=True); sys.exit(1)
for o in objs:
    target = dest / o['path'][len(prefix):]
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.part')
    q = urllib.parse.urlencode({'path': o['path']})
    with get('/repositories/%s/refs/%s/objects?%s' % (repo, ref, q)) as r, open(str(part), 'wb') as fh:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    if part.stat().st_size != o['size_bytes']:
        print('checkpoint stage-in: short download of', o['path'], flush=True); sys.exit(1)
    os.replace(str(part), str(target))
print('checkpoint stage-in: %d files from %s@%s %s' % (len(objs), repo, ref[:12], prefix), flush=True)
"""

import base64, hashlib, json, os, re, shlex, signal, subprocess, sys, threading, time, urllib.parse, urllib.request

# F-04 stage-in, run ON the compute node (system python3, stdlib only):
# take the commit dataset-loading pinned (DATASET_COMMIT) or resolve
# ref -> commit, download the dataset (data.yaml, images/, labels/ at the root of
# the dataset repository) of that version from the lakeFS PUBLIC
# endpoint (bearer through oauth2-proxy — the in-cluster S3-gateway/manifest
# streaming path is blocked by the SSO front off-cluster) into a Lustre cache
# keyed by commit, parallel + resumable (size-matched files are skipped,
# per-writer part-file renamed atomically). Rides to the node base64-encoded in the job
# environment.
STAGEIN = """
import concurrent.futures, json, os, pathlib, sys, urllib.parse, urllib.request
EP = os.environ['LAKEFS_ENDPOINT'].rstrip('/')
H = {'Authorization': 'Bearer ' + os.environ['LAKEFS_BEARER_TOKEN']}
REPO, REF = os.environ['DATASET_REPO'], os.environ['DATASET_REF']
def get(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=H), timeout=120)
base = EP + '/api/v1/repositories/' + urllib.parse.quote(REPO, safe='')
# The commit dataset-loading pinned, so this step reads exactly what the
# in-cluster steps read. Without one (older step code): ref -> tip commit via
# the commit LOG (amount=1). GET /refs/{ref} does not exist on our lakeFS
# version (404, live job 5143633) — /refs/{ref}/commits is the proven one.
commit = os.environ.get('DATASET_COMMIT') or json.load(
    get(base + '/refs/' + urllib.parse.quote(REF, safe='')
        + '/commits?amount=1'))['results'][0]['id']
dest = pathlib.Path(os.environ['DATASET_CACHE']) / REPO / commit
open(os.environ['DATASET_DIRFILE'], 'w').write(str(dest))
if (dest / '.complete').exists():
    (dest / '.complete').touch()            # last use, for the job's cache cleanup
    (dest / '.kaos-commit').write_text(commit)  # the kubecore consumer checks it
    print('stage-in: cache hit', dest, flush=True)
    sys.exit(0)
def ls(prefix):
    objs, after = [], ''
    while True:
        page = json.load(get(base + '/refs/' + commit + '/objects/ls?'
                             + urllib.parse.urlencode(
                                 {'amount': 1000, 'after': after,
                                  'prefix': prefix})))
        objs += [r for r in page.get('results') or []
                 if r.get('path_type') == 'object']
        pg = page.get('pagination') or {}
        if not pg.get('has_more'):
            return objs
        after = pg.get('next_offset') or ''
# Only the dataset: the repository root may also hold other files (README,
# notes) the steps never read.
objs = [o for o in ls('') if o['path'] == 'data.yaml'
        or o['path'].split('/', 1)[0] in ('images', 'labels')]
print('stage-in:', len(objs), 'objects @', commit[:12], flush=True)
def fetch(o):
    p = dest / o['path']
    if p.exists() and p.stat().st_size == o.get('size_bytes'):
        return 0
    p.parent.mkdir(parents=True, exist_ok=True)
    # PRD-1609 F-02: one part-file per writer — another job may stage the same file.
    tmp = '%s.part-%s-%d' % (p, os.environ.get('SLURM_JOB_ID', ''), os.getpid())
    try:
        with get(base + '/refs/' + commit + '/objects?'
                 + urllib.parse.urlencode({'path': o['path']})) as r:
            with open(tmp, 'wb') as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return 1
with concurrent.futures.ThreadPoolExecutor(8) as ex:
    n = sum(ex.map(fetch, objs))
(dest / '.complete').touch()
(dest / '.kaos-commit').write_text(commit)   # the kubecore consumer checks it
print('stage-in: downloaded', n, 'of', len(objs), '->', dest, flush=True)
"""

# F-08 wallet: mint a short-lived Zitadel bearer from the mounted machine
# key — the same JWT-profile recipe as the seeded mlflow_zitadel_auth
# module (assertion aud = https://{domain}; the project-audience scope is
# what makes the token acceptable to mlflow-oidc-auth AND carries the
# groups claim). PyJWT+cryptography are pip-installed at run time: the
# submit image is bare-stdlib alpine and RS256 needs real crypto. Any
# failure degrades loudly to no-wallet (job still runs, data-plane env
# omitted) — never the machine key itself into the Slurm environment
# (T-03: HPC-side env must only ever see short-lived tokens).
WALLET = None
WALLET_EXP = 0.0
# Resubmit a still-PENDING job before its wallet (MLflow/lakeFS bearer, 12 h
# lifetime) expires: a job that starts after a queue wait longer than the
# wallet would train blind (no MLflow, no checkpoint upload, no stage-out).
# The Slurm JWT is read fresh per request (tok()); the wallet cannot be
# refreshed inside a queued job, so the job itself is replaced.
WALLET_MARGIN_S = 30 * 60
# PRD-HPC-1461 D-44 (amended 2026-11-05): only a step declared resumable gets the stop signal,
# this many minutes before its wall time, and continues in a new job; 0 = not resumable.
RESUMABLE_LEAD_MIN = int(os.environ.get('HPC_RESUMABLE_LEAD') or 0)
ATTEMPT = 1      # this step's job: 1, then one more per continuation
# PRD-HPC-1461 D-44: exit 85 = the step saved its checkpoint; it continues in a new job at most
# MAX_CONTINUATIONS times (the render's HPC_MAX_CONTINUATIONS sizes the waiter's deadline for them).
CHECKPOINT_EXIT = 85
MAX_CONTINUATIONS = 5
RESUME = None    # (commit, path) of the checkpoint the next job continues from
OFFER_S = 60   # PRD-1609: a sharing job waits this long for a host of its scope to take it


def wallet_exp(w):
    """exp claim of a JWT as epoch seconds (0 when unknown)."""
    try:
        seg = w.split('.')[1]
        return float(json.loads(base64.urlsafe_b64decode(
            seg + '=' * (-len(seg) % 4)))['exp'])
    except Exception:
        return 0.0


def mint_wallet():
    keyfile = os.environ.get('ZITADEL_MACHINE_KEY_FILE') or ''
    domain = os.environ.get('ZITADEL_DOMAIN') or ''
    if not keyfile or not os.path.exists(keyfile) or not domain:
        print('wallet: machine key / domain absent, data-plane env omitted',
              flush=True)
        return ''
    try:
        import subprocess
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q',
                        '--no-warn-script-location', '--root-user-action',
                        'ignore', 'PyJWT', 'cryptography'],
                       check=True, timeout=180)
        import jwt as pyjwt
        key = json.load(open(keyfile))
        now = int(time.time())
        assertion = pyjwt.encode(
            {'iss': key['userId'], 'sub': key['userId'],
             'aud': 'https://' + domain, 'iat': now, 'exp': now + 60},
            key['key'], algorithm='RS256', headers={'kid': key['keyId']})
        scope = 'openid email profile urn:zitadel:iam:org:projects:roles'
        pid = os.environ.get('ZITADEL_MLFLOW_PROJECT_ID') or ''
        if pid:
            scope += ' urn:zitadel:iam:org:project:id:' + pid + ':aud'
        req = urllib.request.Request(
            'https://' + domain + '/oauth/v2/token',
            data=urllib.parse.urlencode({
                'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                'scope': scope, 'assertion': assertion}).encode())
        tok = json.load(urllib.request.urlopen(req, timeout=30)).get(
            'access_token', '')
        print('wallet: minted' if tok else 'wallet: empty token response',
              flush=True)
        return tok
    except Exception as e:
        print('wallet: mint failed, data-plane env omitted:', e, flush=True)
        return ''

# OCI WORKDIR (live job 5148071): Docker honours the image's WorkingDir,
# Apptainer does NOT — `apptainer exec` starts in the host cwd, so a step
# command like `python -m app.entry` fails with "No module named 'app'".
# Step images use different WORKDIRs (/app, /work), so it is read from the
# image config in the registry at submit time and passed as `--pwd`.
# Best-effort: any failure yields '' (no --pwd), never a blocked submit.
def fetch_workdir(image, reg_token):
    try:
        ref_host, _, rest = image.partition('/')
        if '@' in rest:
            path, ref = rest.split('@', 1)
        elif ':' in rest.rsplit('/', 1)[-1]:
            path, ref = rest.rsplit(':', 1)
        else:
            path, ref = rest, 'latest'
        hdr = {'Accept': ', '.join([
            'application/vnd.oci.image.index.v1+json',
            'application/vnd.docker.distribution.manifest.list.v2+json',
            'application/vnd.oci.image.manifest.v1+json',
            'application/vnd.docker.distribution.manifest.v2+json'])}
        if reg_token and ref_host.endswith('-docker.pkg.dev'):
            hdr['Authorization'] = 'Bearer ' + reg_token
        base = 'https://' + ref_host + '/v2/' + path

        def get(url):
            return json.load(urllib.request.urlopen(
                urllib.request.Request(url, headers=hdr), timeout=20))
        m = get(base + '/manifests/' + ref)
        if 'manifests' in m:  # multi-arch index: pick linux/amd64
            pick = next((x for x in m['manifests']
                         if (x.get('platform') or {}).get('architecture') == 'amd64'
                         and (x.get('platform') or {}).get('os', 'linux') == 'linux'),
                        m['manifests'][0])
            m = get(base + '/manifests/' + pick['digest'])
        cfg = get(base + '/blobs/' + m['config']['digest'])
        wd = (cfg.get('config') or {}).get('WorkingDir') or ''
        print('workdir:', wd or '(none)', flush=True)
        return wd
    except Exception as e:
        print('workdir: lookup failed (running from host cwd):', e, flush=True)
        return ''


# PRD-1609 node sharing. Off unless the operator turned it on for this project
# (pipeline context hpc.sharing) and gave its scope: a host on a shared node takes
# only jobs whose name and script header carry its own scope.
SCOPE = os.environ.get('HPC_SCOPE') or ''
SHARING = os.environ.get('HPC_SHARING') == 'on' and re.fullmatch('[a-z0-9]{8,16}', SCOPE) is not None
if os.environ.get('HPC_SHARING') == 'on' and not SHARING:
    print('node sharing: scope %r is not 8-16 lowercase letters or digits - running alone' % SCOPE,
          flush=True)
if SHARING and RESUMABLE_LEAD_MIN:
    # A step on a shared node is not passed the stop signal (#1609), so a resumable step runs alone.
    print('node sharing: off for this step - it is resumable', flush=True)
    SHARING = False
# What stays in the Slurm environment when the inputs move into the script: the
# login shell builds PATH from it, so it is never re-exported over the profile.
SLURM_ENV_KEEP = ('PATH', 'HOME', 'USER')


def inputs_in_script(batch, env):
    """D-02: a host can read a waiting job's script, never its environment (probe
    2026-11-03), so with sharing on the step's inputs ride in the script as export
    lines after its header, and the Slurm environment keeps only SLURM_ENV_KEEP."""
    keep, exports = [], []
    for e in env:
        k, v = e.split('=', 1)
        if k in SLURM_ENV_KEEP:
            keep.append(e)
        else:
            exports.append('export %s=%s' % (k, shlex.quote(v)))
    lines = batch.split('\n')
    return '\n'.join(lines[:3] + exports + lines[3:]), keep


def comment_of(job):
    """The job comment: a string from slurmctld, {'job': ...} from slurmdbd."""
    c = job.get('comment') or ''
    return (c.get('job') or '') if isinstance(c, dict) else c


def share_state(comment):
    """D-04: what a host wrote into this job's comment, as a dict ({} when no host
    took it): kaos-state (taken|done|requeued), host, slot, attempt, rc, reason."""
    return dict(re.findall(r'(?:^|\s)(kaos-state|host|slot|attempt|rc|reason)=(\S+)', comment))


# PRD-1609 F-03: the slot manager. With sharing on, a job's batch step runs this
# instead of its own step (MeluXina compute nodes: Python 3.6, standard library only).
# It runs its own step and waiting jobs of the same scope as Slurm job steps, one GPU
# each, and reports each in that job's comment. Rides to the node base64-encoded.
SLOTS = r"""
import os, re, signal, subprocess, sys, time

# A step's environment: Slurm's own variables, the GPU it was given and the login
# basics. Nothing of the host's inputs reaches a guest; each script exports its own.
STEP_ENV = re.compile(r'^(SLURM_|CUDA_VISIBLE_DEVICES$|GPU_DEVICE_ORDINAL$|ROCR_VISIBLE_DEVICES$'
                      r'|KUBECORE_SLOT_|PATH$|HOME$|USER$|LANG$|LC_)')

if sys.argv[1:2] == ['--step']:
    import pwd
    script, job = sys.argv[2], sys.argv[3]
    env = dict((k, v) for k, v in os.environ.items() if STEP_ENV.match(k))
    # The login basics, also when Slurm passed none (SLURM_EXPORT_ENV=NONE).
    me = pwd.getpwuid(os.getuid())
    env.setdefault('HOME', me.pw_dir)
    env.setdefault('USER', me.pw_name)
    env.setdefault('PATH', '/usr/bin:/bin:/usr/local/bin')
    env.update(KAOS_IN_STEP='1', KAOS_JOB_ID=job)
    os.chdir(env.get('HOME') or '/')
    if len(sys.argv) > 4:
        # The step writes its own log: srun forwards output late, and fail() reads
        # this file for the job's comment (live 2026-11-03: the hosted tail was empty).
        fd = os.open(sys.argv[4], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
        os.dup2(fd, 1)
        os.dup2(fd, 2)
    os.execve('/bin/bash', ['bash', '-l', script], env)

ME = os.environ['SLURM_JOB_ID']
OWN_SCRIPT = sys.argv[1]
SCOPE = os.environ['KAOS_SCOPE']
PREFIX = 'kaos-' + SCOPE + '-'
HEADER = '# kaos-job v2 scope=' + SCOPE
CLAIMS = os.path.join(os.environ['KAOS_SCR'], 'kaos-claims')
HOME = os.environ.get('HOME') or '/'
GPUS = max(1, int(os.environ.get('HPC_GPUS') or 1))
CPUS = max(1, int(os.environ.get('SLURM_CPUS_ON_NODE') or GPUS) // GPUS)
IDLE_S = int(os.environ.get('KAOS_IDLE_S') or 120)
MARGIN_S = 300          # a guest must end this long before the host's own limit
TOKEN_MARGIN_S = 1800   # ... and this long before its own token expires (D-07)
# Not takeable: held (another host took it) or waiting for another job. A job of this
# scope waiting for its BeginTime is in its offer window (OFFER_S): exactly the job a
# host should take, so it is NOT skipped.
HELD = ('JobHeld', 'Dependency')
POLL_S = float(os.environ.get('KAOS_POLL_S') or 2)   # watchdog cadence; queue every 5 polls


def log(*a):
    print(time.strftime('%H:%M:%S'), 'slots:', *a, flush=True)


def run(*cmd):
    p = subprocess.run(list(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       universal_newlines=True)
    return p.returncode, p.stdout.strip()


def q(job, fmt):
    rc, out = run('squeue', '-h', '-j', job, '-o', fmt)
    return out if rc == 0 else ''


def comment(job):
    c = q(job, '%k')
    return '' if c == '(null)' else c


def set_comment(job, text):
    run('scontrol', 'update', 'JobId=' + job, 'Comment=' + text)


def lease(c):
    m = re.search(r'kaos-commit=\S+', c)
    return m.group(0) + ' ' if m else ''


def err_part(c):
    m = re.search(r'(?:^|\s)(err\d+:.*)$', c)
    return ' ' + m.group(1) if m else ''


def attempt(c):
    m = re.search(r'(?:^|\s)attempt=(\d+)', c)
    return int(m.group(1)) if m else 1


def mem_share_bytes():
    mb = int(os.environ.get('SLURM_MEM_PER_NODE') or 0)
    if not mb:
        with open('/proc/meminfo') as f:
            mb = int(f.readline().split()[1]) // 1024
    return mb * 1024 * 1024 // GPUS


def limit_s(text):
    # squeue %l: UNLIMITED, D-HH:MM:SS, HH:MM:SS, MM:SS or MM
    if not text or text in ('UNLIMITED', 'INVALID', 'NOT_SET'):
        return None
    days, _, rest = text.rpartition('-')
    try:
        parts = [int(x) for x in rest.split(':')]
    except ValueError:
        return None
    if len(parts) == 1:
        h, m, s = 0, parts[0], 0
    elif len(parts) == 2:
        h, m, s = 0, parts[0], parts[1]
    else:
        h, m, s = parts[-3:]
    return int(days or 0) * 86400 + h * 3600 + m * 60 + s


def end_epoch():
    e = q(ME, '%e')
    try:
        return time.mktime(time.strptime(e, '%Y-%m-%dT%H:%M:%S'))
    except ValueError:
        return time.time() + 3600


PART = q(ME, '%P')
HOST_END = end_epoch()
SHARE = mem_share_bytes()
PAGE = os.sysconf('SC_PAGE_SIZE')
slots = {}      # slot -> {'job', 'proc', 'claim', 'name', 'memkill'}
own_rc = None
skip = set()    # jobs looked at and not ours to take


def launch(slot, job, script, log_to, limit=None):
    # --export=ALL: a job with an explicit environment (REST) has SLURM_EXPORT_ENV=NONE,
    # and a plain srun would start the step without HOME or PATH (live 2026-11-03,
    # job 5417729). The launcher then keeps only Slurm's variables and the basics.
    cmd = ['srun', '--export=ALL', '--exact', '-N1', '-n1', '--gpus=1', '-c', str(CPUS),
           '--job-name', 'kaos-' + job]
    if limit:
        cmd.append('--time=%d' % max(1, (limit + 59) // 60))
    cmd += ['python3', sys.argv[0], '--step', script, job] + ([log_to] if log_to else [])
    out = open(log_to, 'a') if log_to else None
    # PRD-1609 F-05: the step's share of the node, for kaos_lib.runtime (context().slot,
    # usable_cpus()): the GPU is already the only one it sees; cores and memory are not hidden.
    env = dict(os.environ, KUBECORE_SLOT_GPUS='1', KUBECORE_SLOT_CPUS=str(CPUS),
               KUBECORE_SLOT_MEM_GIB=str(SHARE >> 30), KUBECORE_SLOT_SHARED='1')
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT if out else None,
                            env=env)
    return proc


def step_id(job):
    rc, out = run('squeue', '-s', '-j', ME, '-h', '-o', '%i %j')
    for line in out.splitlines():
        sid, _, name = line.partition(' ')
        if name == 'kaos-' + job:
            return sid
    return None


def pss_bytes(pid):
    # PSS shares a page between the processes that map it, so the forked data-loader
    # workers of one training are not counted many times over (RSS would be).
    try:
        with open('/proc/%s/smaps_rollup' % pid) as f:
            for line in f:
                if line.startswith('Pss:'):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    with open('/proc/%s/statm' % pid) as f:      # kernels without smaps_rollup
        return int(f.read().split()[1]) * PAGE


def step_rss():
    # Memory per step, from /proc (psslurm has no slurmd tooling: scontrol listpids fails).
    rss = {}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            with open('/proc/%s/environ' % pid, 'rb') as f:
                env = dict(kv.split(b'=', 1) for kv in f.read().split(b'\0') if b'=' in kv)
            if env.get(b'SLURM_JOB_ID') != ME.encode() or b'SLURM_STEP_ID' not in env:
                continue
            used = pss_bytes(pid)
        except (OSError, ValueError, IndexError):
            continue
        sid = env[b'SLURM_STEP_ID'].decode()
        rss[sid] = rss.get(sid, 0) + used
    return rss


def step_limit_of(text):
    # The step's own time limit in seconds, from its script (KAOS_STEP_LIMIT_MIN). Its job
    # asks Slurm for more (padded, so a host has room for guests); the step needs only this.
    m = re.search(r'^export KAOS_STEP_LIMIT_MIN=(\d+)$', text, re.M)
    return int(m.group(1)) * 60 if m else None


def take(slot, job, name, job_limit):
    # Take one waiting job onto slot. Its script is read first (no side effect); only a
    # job of this scope whose STEP fits the host's remaining time and its own token is
    # locked, held and run. A job that does not fit now never will on this host (its
    # remaining time only shrinks), so it is skipped for good.
    now = time.time()
    if not os.path.isdir(CLAIMS):
        os.makedirs(CLAIMS, exist_ok=True)
    peek = os.path.join(CLAIMS, '.peek-%s-%s.sh' % (ME, job))
    rc, _ = run('scontrol', 'write', 'batch_script', job, peek)
    text = open(peek).read() if rc == 0 and os.path.exists(peek) else ''
    try:
        os.remove(peek)
    except OSError:
        pass
    if HEADER not in text.split('\n')[:3]:
        skip.add(job)
        log('not taking', job, '(no', HEADER + ')')
        return False
    limit = step_limit_of(text) or job_limit
    m = re.search(r'^export KAOS_TOKEN_EXP=(\d+)$', text, re.M)
    if (limit is None or now + limit + MARGIN_S > HOST_END
            or (m and now + limit + MARGIN_S > int(m.group(1)) - TOKEN_MARGIN_S)):
        skip.add(job)
        return False
    c = comment(job)
    k = attempt(c)
    claim = os.path.join(CLAIMS, '%s-a%d' % (job, k))
    try:
        os.mkdir(claim)
    except OSError:
        return False                       # another host is deciding or runs it
    # The claim folder is a lock: only its owner holds or releases the job, so two
    # hosts never undo each other. A taken job stays held, so it never also starts alone.
    keep = False
    try:
        run('scontrol', 'hold', job)
        if not q(job, '%T|%r').startswith('PENDING|JobHeld'):
            return False                   # it started on its own node meanwhile
        script = os.path.join(claim, 'job.sh')
        rc, _ = run('scontrol', 'write', 'batch_script', job, script)
        if rc != 0 or HEADER not in open(script).read().split('\n')[:3]:
            return False
        set_comment(job, '%skaos-state=taken host=%s slot=%d attempt=%d' % (lease(c), ME, slot, k))
        slots[slot] = {'job': job, 'claim': claim, 'name': name, 'memkill': False, 'attempt': k,
                       'proc': launch(slot, job, script, os.path.join(HOME, 'slurm-%s.out' % job), limit)}
        keep = True
        log('took', job, name, 'on slot', slot)
        return True
    finally:
        if not keep:
            run('scontrol', 'release', job)
            unlock(claim)


def unlock(claim):
    # Remove a claim folder (the lock and the script copy in it).
    if not claim:
        return
    try:
        for f in os.listdir(claim):
            os.remove(os.path.join(claim, f))
        os.rmdir(claim)
    except OSError:
        pass


def requeue(s):
    # Back to the queue with the next attempt number, still leasing its dataset.
    if q(s['job'], '%T') == 'PENDING':
        c = comment(s['job'])
        set_comment(s['job'], '%skaos-state=requeued attempt=%d' % (lease(c), s['attempt'] + 1))
        run('scontrol', 'release', s['job'])
        log('requeued', s['job'], 'as attempt', s['attempt'] + 1)
    unlock(s.get('claim'))


def finish(slot, rc):
    global own_rc
    s = slots.pop(slot)
    job = s['job']
    reason = ' reason=memkill' if s['memkill'] else ''
    if job == ME:
        own_rc = rc
        c = comment(ME)
        set_comment(ME, '%skaos-state=done rc=%d%s%s' % (lease(c), rc, reason, err_part(c)))
        log('own step ended rc=%d%s' % (rc, reason))
        return
    if q(job, '%T') != 'PENDING':
        log('guest', job, 'was stopped; its step ended rc=%d' % rc)
        unlock(s.get('claim'))
        return
    if q(ME, '%T') != 'RUNNING':
        # The host itself is going away (cancelled, out of time): Slurm may end the
        # steps before this program's TERM handler runs (live 2026-11-03, host
        # 5417697). The guest's run did not fail; it goes back to the queue.
        requeue(s)
        return
    c = comment(job)
    set_comment(job, '%skaos-state=done rc=%d host=%s%s%s' % (lease(c), rc, ME, reason, err_part(c)))
    run('scancel', job)
    unlock(s.get('claim'))
    log('guest', job, 'done rc=%d%s' % (rc, reason))


def requeue_all(signum, frame):
    # Host cancelled or out of time (Slurm sends TERM, KILL 30 s later): every guest
    # goes back to the queue with the next attempt number, still leasing its dataset.
    for s in list(slots.values()):
        if s['job'] != ME:
            requeue(s)
    sys.exit(own_rc if own_rc is not None else 143)


signal.signal(signal.SIGTERM, requeue_all)
slots[0] = {'job': ME, 'claim': None, 'name': 'own', 'memkill': False, 'attempt': 1,
            'proc': launch(0, ME, OWN_SCRIPT, None, int(os.environ.get('KAOS_STEP_LIMIT_MIN') or 0) * 60 or None)}
log('host', ME, 'partition', PART, 'slots', GPUS, 'cpus/slot', CPUS, 'mem/slot %d MiB' % (SHARE >> 20))
idle_since, tick = None, 0
while True:
    time.sleep(POLL_S)
    tick += 1
    for slot, s in list(slots.items()):
        rc = s['proc'].poll()
        if rc is not None:
            finish(slot, rc)
    rss = step_rss()
    for s in slots.values():
        sid = s.get('sid') or step_id(s['job'])
        s['sid'] = sid
        if sid and rss.get(sid.split('.')[-1], 0) > SHARE and not s['memkill']:
            log('memory: step', sid, 'of', s['job'], 'uses %d MiB > %d MiB share' % (rss[sid.split('.')[-1]] >> 20, SHARE >> 20))
            s['memkill'] = True
            run('scancel', sid)
    if tick % 5:
        continue
    for slot, s in list(slots.items()):
        if s['job'] != ME and q(s['job'], '%T') != 'PENDING' and s.get('sid'):
            log('guest', s['job'], 'stopped by its run: cancelling step', s['sid'])
            run('scancel', s['sid'])
    if q(ME, '%T') != 'RUNNING':
        # Cancelled or out of time: take nothing new; leave once the last step is gone.
        if not slots:
            sys.exit(own_rc if own_rc is not None else 143)
        continue
    free = [i for i in range(GPUS) if i not in slots]
    if free:
        rc, out = run('squeue', '-u', os.environ.get('USER', ''), '-h', '-t', 'PENDING',
                      '--sort=-p,i', '-o', '%i|%j|%r|%l|%P')
        for line in out.splitlines():
            if not free:
                break
            job, name, reason, lim, part = (line.split('|') + [''] * 5)[:5]
            if (job == ME or job in skip or not name.startswith(PREFIX) or part != PART
                    or reason.startswith(HELD)):
                continue
            if take(free[0], job, name, limit_s(lim)):
                free.pop(0)
    busy = bool(slots)
    if busy:
        idle_since = None
    elif idle_since is None:
        idle_since = time.time()
    elif time.time() - idle_since >= IDLE_S or HOST_END - time.time() < MARGIN_S + 60:
        log('idle: releasing the node')
        sys.exit(own_rc or 0)
"""


API = 'https://slurm-api.lxp.lu/slurm/v0.0.44'
SDB = 'https://slurm-api.lxp.lu/slurmdb/v0.0.44'
TOKEN_FILE = '/etc/meluxina-jwt/token'


def tok():
    """The MeluXina JWT, read FRESH on every request. The platform mints it
    with a 60-minute lifetime and rotates the Secret every 25 minutes; the
    mounted file follows the rotation, an env var does not (live run
    app-meluxina-toy-abcde: the pod's env token expired 13:30:02 while
    the job still queued — every poll 502/511 for hours, and cancel/resubmit
    would have failed the same way)."""
    try:
        with open(TOKEN_FILE) as f:
            t = f.read().strip()
            if t:
                return t
    except OSError:
        pass
    return os.environ['SLURM_TOKEN'].strip()


def hpc_identity():
    """The project's HPC identity from the pipeline context (PRD-HPC-1231
    CON-05): user, account, scratch root and home. Never literals — one
    project's twin must never submit as another project's user. Missing
    identity = the platform did not publish the tenancy; fail loudly."""
    ident = {k: (os.environ.get(v) or '') for k, v in (
        ('user', 'HPC_USER'), ('account', 'HPC_ACCOUNT'),
        ('scratch', 'HPC_SCRATCH'), ('home', 'HPC_HOME'))}
    missing = [k for k, val in ident.items() if not val]
    if missing:
        print('HPC identity missing from the pipeline context:', missing,
              '- the KubeProject is not bound to an HPC tenancy (PRD-HPC-1231)',
              flush=True)
        sys.exit(2)
    return ident


def hdrs():
    return {'X-SLURM-USER-NAME': hpc_identity()['user'],
            'X-SLURM-USER-TOKEN': tok(),
            'Content-Type': 'application/json'}


def hpc_class():
    """The HPC class this twin runs on (its {step}-class value), resolved
    against the catalog the enhancer embedded. Unknown class = render/
    submit mismatch, never a silent default partition."""
    name = os.environ.get('HPC_CLASS') or ''
    for c in json.loads(os.environ.get('HPC_CLASSES_JSON') or '[]'):
        if c.get('name') == name:
            return c
    print('unknown HPC class', repr(name), '- catalog:',
          [c.get('name') for c in json.loads(os.environ.get('HPC_CLASSES_JSON') or '[]')],
          flush=True)
    sys.exit(2)



def get(url):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers=hdrs()), timeout=30))

jobname = 'kaos-' + (SCOPE + '-' if SHARING else '') + os.environ['WF_UID'] + '-' + os.environ['STEP_NAME']
img = os.environ['IMAGE_REF']
# Apptainer rejects tag@digest refs ('Docker references with both a tag and
# digest are currently not supported', live job 5140397). The platform pins
# images as name:tag@sha256:... (Zot-retention lesson) — normalize to the
# digest-only form, which Apptainer accepts and which is the stronger pin.
if '@' in img:
    name, digest = img.split('@', 1)
    if ':' in name.rsplit('/', 1)[-1]:
        name = name.rsplit(':', 1)[0]
    img = name + '@' + digest
# shlex-quote each argv token: the joined string rides through Slurm env ->
# sh -c, and a naive join destroys embedded quoting (live job 5140493:
# python -c 'import torch; ...' arrived as bare words and exited 2).
# strict=False tolerates control characters inside strings — belt-and-braces
# for any substitution path the render-side toJson escaping didn't cover.
cmd = ' '.join(shlex.quote(t) for t in json.loads(
    os.environ.get('STEP_COMMAND') or '[]', strict=False))


def pinned_commit():
    """The lakeFS commit an upstream step recorded as `dataset_commit` in a JSON
    output that rides in this step's own command (e.g. --training-result,
    --dataset-info). The HPC copy then stages exactly what the in-cluster steps
    read. "" when no argument carries one (the first step: see resolve_commit)."""
    toks = json.loads(os.environ.get('STEP_COMMAND') or '[]', strict=False)
    for tok in toks:
        if not (isinstance(tok, str) and tok.lstrip().startswith('{')):
            continue
        try:
            commit = str(json.loads(tok).get('dataset_commit') or '')
        except (ValueError, AttributeError):
            continue
        if commit:
            return commit
    return ''


def dataset_coords():
    """(repo, ref) of the run's `dataset` parameter (`<dataset-repo>@<version>`):
    the dataset repository and the lakeFS ref to resolve when no commit was
    pinned (`latest` is the head of `main`). ('', '') when the pipeline has no
    `dataset` parameter (the batch then runs the step data-less)."""
    value = (os.environ.get('DATASET') or '').strip()
    if not value:
        return '', ''
    repo, sep, version = value.partition('@')
    if not (sep and re.match(r'^dataset-[a-z0-9][a-z0-9-]*$', repo)
            and re.match(r'^(latest|v[0-9]+)$', version)):
        print('dataset must be <dataset-repo>@<version> (e.g. '
              'dataset-default@latest), got %r' % value, flush=True)
        sys.exit(1)
    return repo, ('main' if version == 'latest' else version)


def resolve_commit(repo, ref, lakefs, wallet):
    """ref -> commit for a first step that has no upstream pin. The commit log
    (amount=1) is the proven endpoint: GET /refs/{ref} does not exist on our
    lakeFS version. Tags and branches both work as {ref}."""
    url = (lakefs + '/api/v1/repositories/' + urllib.parse.quote(repo, safe='')
           + '/refs/' + urllib.parse.quote(ref, safe='') + '/commits?amount=1')
    page = json.load(urllib.request.urlopen(urllib.request.Request(
        url, headers={'Authorization': 'Bearer ' + wallet}), timeout=60))
    return page['results'][0]['id']


PINNED = ''   # the commit staged for this run (upstream pin, else resolved here)


# PRD-HPC-1541 F-03: stage the pinned dataset commit into the project's Lustre
# cache from a MeluXina LOGIN node before the GPU job is submitted, so the job
# reads a resident copy instead of downloading on GPU time. The pod talks to
# the stager the platform installed (~/.kaos/stager.py) through a
# forced-command key that can run nothing else (Secret meluxina-staging: key +
# verified host pin). The stager names a base (its newest ready commit of the
# repo); the pod lists only the lakeFS diff base..commit, or the whole
# dataset for a first copy, and streams one JSON line per file. Unchanged
# files are hard links of the base. Bytes come from the lakeFS API with the
# wallet bearer (sent once on stdin, held in memory only) until presigned URLs
# are enabled (F-05). Any failure returns '' and the job stages in-job as
# before, saying so (F-06).
STAGING_DIR = '/etc/meluxina-staging'
LOGIN_HOST, LOGIN_PORT = 'login.lxp.lu', '8822'
STAGE_BUDGET_S = 4 * 3600
EX_RETRY, EX_NOSPACE = 75, 76


def lakefs_pages(url, wallet, params):
    # Every object of a paginated lakeFS listing (objects/ls or diff).
    after = ''
    while True:
        q = urllib.parse.urlencode(dict(params, amount=1000, after=after))
        page = json.load(urllib.request.urlopen(urllib.request.Request(
            url + '?' + q, headers={'Authorization': 'Bearer ' + wallet}), timeout=120))
        for r in page.get('results') or []:
            if r.get('path_type') == 'object':
                yield r
        pg = page.get('pagination') or {}
        if not pg.get('has_more'):
            return
        after = pg.get('next_offset') or ''


def is_dataset_path(path):
    # The YOLO layout the steps read: data.yaml, images/, labels/ at the
    # root of the dataset repository. README and notes are not staged.
    return path == 'data.yaml' or path.split('/', 1)[0] in ('images', 'labels')


def stage_plan(api, commit, base, prefix, wallet):
    # (kind, path, size) per file the stager applies: the two-dot diff against
    # the base (three-dot would be wrong when the base is not an ancestor), or
    # every object of the commit for a first copy.
    if base:
        for d in lakefs_pages(api + '/refs/%s/diff/%s' % (base, commit), wallet,
                              {'prefix': prefix, 'type': 'two_dot'}):
            if d['type'] not in ('added', 'changed', 'removed'):
                raise ValueError('unexpected diff entry %s for %s' % (d['type'], d['path']))
            if is_dataset_path(d['path']):
                yield d['type'], d['path'], int(d.get('size_bytes') or 0)
    else:
        for o in lakefs_pages(api + '/refs/%s/objects/ls' % commit, wallet, {'prefix': prefix}):
            if is_dataset_path(o['path']):
                yield 'added', o['path'], int(o.get('size_bytes') or 0)


def stager(words, feed=None):
    # One stager subcommand on a login node: (exit code, JSON events). The
    # feed's records are written while the stager downloads; a feed that
    # fails mid-way closes stdin without the end record, which the stager
    # keeps as resumable partial state (exit 75).
    cmd = ['ssh', '-i', STAGING_DIR + '/id_ed25519', '-p', LOGIN_PORT,
           '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'UserKnownHostsFile=' + STAGING_DIR + '/known_hosts',
           '-o', 'ConnectTimeout=20', '-o', 'ServerAliveInterval=30',
           '-o', 'ServerAliveCountMax=4',
           hpc_identity()['user'] + '@' + LOGIN_HOST,
           ' '.join(shlex.quote(str(w)) for w in words)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE if feed is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         universal_newlines=True)
    events = []

    def read():
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                print('stager:', line.rstrip(), flush=True)
                continue
            events.append(ev)
            print('stager:', json.dumps(ev, sort_keys=True), flush=True)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    failed = None
    if feed is not None:
        try:
            for rec in feed:
                p.stdin.write(json.dumps(rec) + '\n')
        except BrokenPipeError:
            pass
        except Exception as e:
            failed = e
        try:
            p.stdin.close()
        except BrokenPipeError:
            pass
    rc = p.wait()
    reader.join(30)
    err = p.stderr.read().strip()
    if err:
        print('stager stderr:', err[-2000:], flush=True)
    if failed is not None:
        raise failed
    return rc, events


def stage_once(repo, ref, commit, lakefs, wallet):
    # One staging attempt. Returns (path, retry): the ready path, or '' with
    # whether a later attempt can help.
    rc, ev = stager(['status', '--repo', repo, '--commit', commit, '--ref', ref])
    st = next((e for e in reversed(ev) if e.get('event') == 'status'), None)
    if rc != 0 or st is None:
        return '', rc in (EX_RETRY, 255)
    if st.get('ready'):
        print('stage: cache hit', st['path'], flush=True)
        return st['path'], False
    api = lakefs + '/api/v1/repositories/' + urllib.parse.quote(repo, safe='')
    # The dataset sits at the repository root; is_dataset_path() keeps the rest out.
    prefix = ''
    base = st.get('base') if st.get('base') and st.get('base_prefix') == prefix else None
    need_bytes = need_files = added = removed = 0
    for kind, _, size in stage_plan(api, commit, base, prefix, wallet):
        if kind == 'removed':
            removed += 1
            continue
        need_bytes += size
        need_files += 1
        added += kind == 'added'
    files = (int(st.get('base_files') or 0) if base else 0) + added - removed
    print('stage: %s@%s %s: %d files to fetch (%.1f MB), %d to delete, %d in the version'
          % (repo, commit[:12], 'delta on ' + base[:12] if base else 'first copy',
             need_files, need_bytes / 1e6, removed, files), flush=True)

    def feed():
        yield {'op': 'auth', 'authorization': 'Bearer ' + wallet}
        for kind, path, size in stage_plan(api, commit, base, prefix, wallet):
            if kind == 'removed':
                yield {'op': 'delete', 'path': path}
            else:
                yield {'op': 'fetch', 'path': path, 'size': size,
                       'url': api + '/refs/' + commit + '/objects?'
                       + urllib.parse.urlencode({'path': path})}
        yield {'op': 'end', 'files': files, 'bytes': need_bytes, 'ref': ref, 'prefix': prefix}
    words = ['stage', '--repo', repo, '--commit', commit, '--ref', ref,
             '--need-bytes', need_bytes, '--need-files', need_files]
    if base:
        words += ['--base', base]
    rc, ev = stager(words, feed())
    done = next((e for e in reversed(ev) if e.get('event') == 'done'), None)
    if rc == 0 and done:
        return done['path'], False
    if rc == EX_NOSPACE:
        print('stage: NOT ENOUGH SPACE on MeluXina scratch for this version even after'
              ' evicting unused versions - free space or raise the quota', flush=True)
    return '', rc in (EX_RETRY, 255)


def stage_dataset():
    # The resident path of the pinned commit, or '' (job stages in-job).
    global PINNED
    repo, ref = dataset_coords()
    commit = PINNED = pinned_commit()
    lakefs = (os.environ.get('LAKEFS_EXTERNAL_URL') or '').rstrip('/')
    if not (repo and lakefs and os.path.exists(STAGING_DIR + '/id_ed25519')):
        print('stage: skipped (needs the dataset parameter, the lakeFS'
              ' endpoint and the staging key) - the job stages in-job', flush=True)
        return ''
    wallet = mint_wallet()
    if not wallet:
        return ''
    if not commit:
        # The first step of the run: nothing upstream pinned a commit, so pin it
        # here (the step then resolves the same ref; a vN tag cannot move).
        try:
            commit = PINNED = resolve_commit(repo, ref, lakefs, wallet)
        except Exception as e:
            print('stage: cannot resolve %s@%s (%s) - the job stages in-job' % (repo, ref, e), flush=True)
            return ''
    try:
        if subprocess.call(['sh', '-c', 'command -v ssh >/dev/null || apk add --no-cache -q openssh-client']) != 0:
            print('stage: no ssh client - the job stages in-job', flush=True)
            return ''
    except OSError as e:
        print('stage: no ssh client (%s) - the job stages in-job' % e, flush=True)
        return ''
    deadline, attempt = time.time() + STAGE_BUDGET_S, 0
    while True:
        attempt += 1
        try:
            path, retry = stage_once(repo, ref, commit, lakefs, wallet)
        except Exception as e:
            print('stage: attempt', attempt, 'failed:', e, flush=True)
            path, retry = '', True
        if path or not retry or time.time() > deadline:
            break
        time.sleep(min(60 * attempt, 600))
    if not path:
        print('stage: NOT STAGED - the job will download the dataset in-job on GPU time',
              flush=True)
    return path

jid = None


def find_active():
    for j in (get(API + '/jobs').get('jobs') or []):
        st = j.get('job_state') or []
        if j.get('name') == jobname and any(
                x in ('PENDING', 'RUNNING', 'SUSPENDED') for x in st):
            return j.get('job_id')
    return None


STAGED, STAGE_TRIED = '', False


def pull_token():
    # The registry token the job pulls its image with. Own (metadata server)
    # token: the pod's GSA, valid 1 h, so a job that queues longer fails with
    # 231. HPC_PULL_SA (pipeline context hpc.pullServiceAccount) names the org's
    # read-only pull GSA: impersonate it for a 12 h token instead (the CI GSA
    # can push and is never stretched). Any failure falls back to the own
    # token - minting must never fail a submit.
    try:
        r = urllib.request.Request(
            'http://metadata.google.internal/computeMetadata/v1/instance/'
            'service-accounts/default/token',
            headers={'Metadata-Flavor': 'Google'})
        own = json.load(urllib.request.urlopen(r, timeout=5)).get(
            'access_token', '')
    except Exception as e:
        print('no registry token from metadata server (anonymous pull):', e,
              flush=True)
        return ''
    sa = os.environ.get('HPC_PULL_SA', '')
    if not sa or not own:
        return own
    try:
        r = urllib.request.Request(
            'https://iamcredentials.googleapis.com/v1/projects/-/'
            'serviceAccounts/%s:generateAccessToken' % sa,
            data=json.dumps({
                'scope': ['https://www.googleapis.com/auth/cloud-platform'],
                'lifetime': '43200s'}).encode(),
            headers={'Authorization': 'Bearer ' + own,
                     'Content-Type': 'application/json'})
        tok = json.load(urllib.request.urlopen(r, timeout=10)).get(
            'accessToken', '')
        if tok:
            print('registry pull token: 12 h, read-only, as', sa, flush=True)
            return tok
        why = 'empty response'
    except urllib.error.HTTPError as e:
        why = 'HTTP %s %s' % (e.code, e.read()[:300])
    except Exception as e:
        why = e
    print('12 h pull token as %s unavailable (%s); using the 1 h pod token'
          % (sa, why), flush=True)
    return own


def submit():
    global STAGED, STAGE_TRIED
    HPC = hpc_class()
    if not STAGE_TRIED:
        # Once per pod: a resubmit reuses the staged copy (or the in-job
        # fallback) instead of spending the staging budget again.
        STAGE_TRIED = True
        STAGED = stage_dataset()
    reg = pull_token()
    ident = hpc_identity()
    batch = '\n'.join([
        '#!/bin/bash -l',
        # PRD-1609 F-01: the script's format and sharing scope ('-': sharing off).
        # A host takes only jobs whose header carries its own scope.
        '# kaos-job v2 scope=' + (SCOPE if SHARING else '-'),
        'set +e',
        # The job this step belongs to: its own on its own node; on a shared node
        # the host sets it to this step's job. Every per-job path keys on it.
        'KAOS_JOB_ID=${KAOS_JOB_ID:-$SLURM_JOB_ID}',
        # Diagnostics without SSH (live job 5143859: exit 231 with no way to
        # see WHY): on any failure, tail this job's own output file into its
        # job COMMENT — readable over REST from the waiter and by operators.
        # The dataset lease (kaos-commit=, PRD-1541 D-06) stays first.
        'fail(){ scontrol update JobId=$KAOS_JOB_ID Comment="${KAOS_COMMIT:+kaos-commit=$KAOS_COMMIT }err$1:$(tail -c 700 slurm-$KAOS_JOB_ID.out 2>/dev/null | tr "\\n" "|")" 2>/dev/null; exit $1; }',
        # PRD-1609 F-03: with sharing on, the job's batch step is the host. It runs
        # this same script as one Slurm job step per slot (its own step and taken
        # guests' scripts), each with KAOS_IN_STEP=1 and that step's KAOS_JOB_ID.
        'if [ -z "$KAOS_IN_STEP" ] && [ -n "$KAOS_SLOTS_B64" ]; then',
        '  printf %s "$KAOS_SLOTS_B64" | base64 -d > /tmp/kaos-slots-$SLURM_JOB_ID.py',
        '  scontrol write batch_script $SLURM_JOB_ID /tmp/kaos-job-$SLURM_JOB_ID.sh >/dev/null || fail 233',
        '  exec python3 /tmp/kaos-slots-$SLURM_JOB_ID.py /tmp/kaos-job-$SLURM_JOB_ID.sh',
        'fi',
        'for f in /usr/share/lmod/lmod/init/bash /etc/profile.d/lmod.sh; do'
        ' [ -r "$f" ] && source "$f" && break; done',
        'module load Apptainer 2>/dev/null || module load apptainer 2>/dev/null',
        'command -v apptainer >/dev/null || fail 210',
        'SCR=' + ident['scratch'],
        'export APPTAINER_CACHEDIR=$SCR/kaos-apptainer-cache'
        ' APPTAINER_TMPDIR=$SCR/kaos-tmp',
        'mkdir -p $APPTAINER_CACHEDIR $APPTAINER_TMPDIR $SCR/sif-cache',
        'KEY=$(printf %s "$IMAGE_REF" | sha256sum | cut -c1-16)',
        'SIF=$SCR/sif-cache/$KEY.sif',
        # F-04 stage-in: only when the wallet minted AND the run pins a
        # dataset. Fails LOUDLY (exit 232) — silently missing data would
        # surface as a cryptic training error hours later.
        'DATASET_DIR=""',
        # PRD-1541 F-06: the copy staged from a login node, when ready. The
        # marker is written last, so its presence means complete.
        'if [ -n "$DATASET_STAGED" ] && [ -f "$DATASET_STAGED/.kaos-ready" ]; then',
        '  DATASET_DIR=$DATASET_STAGED; touch "$DATASET_DIR/.kaos-used" 2>/dev/null',
        '  echo "dataset: resident copy $DATASET_DIR"',
        'elif [ -n "$LAKEFS_BEARER_TOKEN" ] && [ -n "$LAKEFS_ENDPOINT" ] &&'
        ' [ -n "$DATASET_REPO" ] && [ -n "$DATASET_REF" ] &&'
        ' [ -n "$STAGEIN_B64" ] && command -v python3 >/dev/null; then',
        '  [ -n "$DATASET_STAGED" ] && echo "dataset: WARNING staged copy $DATASET_STAGED'
        ' not ready - downloading in-job on GPU time"',
        '  export DATASET_CACHE=$SCR/data-cache'
        ' DATASET_DIRFILE=$SCR/kaos-tmp/ds-$KAOS_JOB_ID.dir',
        '  printf %s "$STAGEIN_B64" | base64 -d | python3 - || fail 232',
        '  DATASET_DIR=$(cat "$DATASET_DIRFILE" 2>/dev/null)',
        'fi',
        # Apptainer passes the host env through, so the wallet/endpoint vars
        # reach the step; the bind gives it the staged version read-only.
        'BIND=""',
        'if [ -n "$DATASET_DIR" ]; then'
        ' BIND="-B $DATASET_DIR:/kubecore/dataset:ro";'
        ' export APPTAINERENV_KUBECORE_DATASET_DIR=/kubecore/dataset'
        ' APPTAINERENV_KUBECORE_STAGED_DIR=/kubecore/dataset; fi',
        # Writable /work: the SIF is read-only, but steps write /work/output
        # (declared outputs), /work/runs, /work/dataset caches. Per-job scratch
        # on Lustre, removed after a successful stage-out.
        'export KAOS_WORK=$SCR/kaos-work/$KAOS_JOB_ID; mkdir -p $KAOS_WORK/output',
        # D-44: a continued job starts from the checkpoint its previous job staged out, never
        # silently from scratch: no checkpoint, no run (exit 234).
        'if [ -n "$KAOS_RESUME_REF" ]; then',
        '  { [ -n "$LAKEFS_BEARER_TOKEN" ] && [ -n "$CKPTIN_B64" ]; } || fail 234',
        '  rm -rf $KAOS_WORK/resume; printf %s "$CKPTIN_B64" | base64 -d | python3 - || fail 234',
        '  export APPTAINERENV_KAOS_RESUME_PATH=/work/resume',
        'fi',
        'BIND="$BIND -B $KAOS_WORK:/work"',
        # Last use of a cached SIF, before the cleanup below can see it.
        'touch -c "$SIF"',
        'if [ ! -f "$SIF" ]; then',
        # GCP token ONLY for GAR hosts: presenting it to Zot turns an
        # anonymous-OK pull into 401 authentication required (live job
        # 5140432 vs the anonymous F-01 pull that worked on the same repo).
        '  case "$IMAGE_REF" in *-docker.pkg.dev/*)'
        ' [ -n "$REG_TOKEN" ] && export'
        ' APPTAINER_DOCKER_USERNAME=oauth2accesstoken'
        ' APPTAINER_DOCKER_PASSWORD=$REG_TOKEN;; esac',
        # PRD-1609 F-02: pull to a name only this job writes, then rename it into
        # the shared cache (atomic on Lustre). Jobs, and steps sharing a node,
        # never run a half-written SIF; an image another job finished first is kept.
        '  SIF_TMP=$SIF.part-$SLURM_JOB_ID-$$',
        '  apptainer pull "$SIF_TMP" docker://$IMAGE_REF || { rm -f "$SIF_TMP"; fail 231; }',
        '  mv -n "$SIF_TMP" "$SIF"; rm -f "$SIF_TMP"',
        'fi',
        # PRD-1541: the image and download caches share the allocation's scratch
        # quota with the dataset cache and only ever grew. This user's entries
        # unused for 14 days go: SIFs, Apptainer's layer cache, in-job
        # downloads. What this job uses was touched just above.
        'find $SCR/sif-cache -maxdepth 1 -name "*.sif" -user "$USER" -mtime +14 -delete 2>/dev/null',
        'find $SCR/sif-cache -maxdepth 1 -name "*.sif.part-*" -user "$USER" -mmin +720 -delete 2>/dev/null',
        'find $SCR/data-cache -mindepth 3 -maxdepth 3 -name .complete -user "$USER" -mtime +14'
        ' -printf "%h\\n" 2>/dev/null | xargs -r rm -rf',
        'apptainer cache clean --force --days 14 >/dev/null 2>&1',
        # Start in the image's WORKDIR (Apptainer ignores it; Docker does not).
        'PWD_OPT=""; [ -n "$STEP_WORKDIR" ] && PWD_OPT="--pwd $STEP_WORKDIR"',
        # --nv only on GPU classes: on the cpu/largemem partitions there is
        # no driver to bind and the flag makes Apptainer warn or fail.
        'NV=""; [ "${HPC_GPUS:-0}" -gt 0 ] && NV="--nv"',
        '[ -n "$STEP_CMD" ] || STEP_CMD="nvidia-smi -L || nproc"',
        # PRD-HPC-1461 D-38/D-44: Slurm sends USR1 to this shell about 10 minutes
        # before the time limit. The step runs in its own process group (set -m), and
        # the shell passes USR1 ONLY to the processes of that group that handle it
        # (SigCgt bit 9): kaos-lib's handler (an open run writer) saves progress and
        # exits 85. Never the whole group: Apptainer's squashfuse dies on USR1 and the
        # image vanishes under the step (live job 5421507: Bus error, rc 135). Inside,
        # sh ignores USR1 and so does every process that keeps that setting, so a step
        # without kaos-lib runs to the limit as before. `wait` returns early on the
        # trap, so wait again until the step is really gone.
        'set -m',
        'apptainer exec $NV $PWD_OPT $BIND "$SIF" /bin/sh -c "trap \'\' USR1; $STEP_CMD" &',
        'STEP_PID=$!',
        'set +m',
        'kaos_stop(){ echo "stop signal: asking the step to save its progress";'
        ' for p in $(pgrep -g $STEP_PID); do'
        ' m=$(awk \'/^SigCgt:/{print $2}\' /proc/$p/status 2>/dev/null);'
        ' [ -n "$m" ] && [ $(( 0x$m >> 9 & 1 )) -eq 1 ] && kill -USR1 $p 2>/dev/null; done; }',
        'trap kaos_stop USR1',
        'wait $STEP_PID; rc=$?',
        'while kill -0 $STEP_PID 2>/dev/null; do wait $STEP_PID; rc=$?; done',
        'trap - USR1',
        # D-44 (amended 2026-11-05, T-19): 85 = a resumable step saved its checkpoint. Before
        # the job ends, the checkpoint goes to the outputs repository and its commit into the
        # job comment; only then may the waiter continue the step. The step's outputs are not
        # final, so nothing else is staged out. 85 from a step that is not resumable fails, and
        # so does a checkpoint that did not upload (exit 235).
        'if [ $rc -eq 85 ]; then',
        '  echo "step saved its checkpoint before the wall time (exit 85)"',
        '  [ "$KAOS_RESUMABLE" = 1 ] || { echo "exit 85, but the step is not declared resumable"; fail 85; }',
        '  { [ -n "$LAKEFS_BEARER_TOKEN" ] && [ -n "$CKPTOUT_B64" ]; } || fail 235',
        '  export KAOS_CKPT_FILE=$KAOS_WORK/.kaos-ckpt',
        '  printf %s "$CKPTOUT_B64" | base64 -d | python3 - || fail 235',
        '  read -r CKPT CKPT_PATH < $KAOS_CKPT_FILE',
        '  scontrol update JobId=$KAOS_JOB_ID Comment="${KAOS_COMMIT:+kaos-commit=$KAOS_COMMIT }'
        'kaos-ckpt=$CKPT kaos-ckpt-path=$CKPT_PATH" || fail 235',
        '  rm -rf "$KAOS_WORK"; exit 85',
        'fi',
        'if [ -n "$STEP_OUTPUTS" ] && [ -n "$STAGEOUT_B64" ] && [ -n "$LAKEFS_BEARER_TOKEN" ]; then'
        ' printf %s "$STAGEOUT_B64" | base64 -d | python3 - || echo "stage-out failed (rc=$rc)"; fi',
        '[ $rc -eq 0 ] && rm -rf "$KAOS_WORK"',
        '[ $rc -ne 0 ] && fail $rc',
        'exit 0',
    ])
    env = ['PATH=/usr/bin:/bin:/usr/local/bin', 'HOME=' + ident['home'],
           'USER=' + ident['user'], 'IMAGE_REF=' + img, 'REG_TOKEN=' + reg,
           'HPC_GPUS=' + str(HPC.get('gpus') or 0),
           'STEP_CMD=' + cmd, 'STEP_WORKDIR=' + fetch_workdir(img, reg),
           'WF_UID=' + (os.environ.get('WF_UID') or ''),
           'STEP_NAME=' + (os.environ.get('STEP_NAME') or ''),
           'STEP_OUTPUTS=' + (os.environ.get('STEP_OUTPUTS') or ''),
           'DATASET_STAGED=' + STAGED, 'KAOS_ATTEMPT=%d' % ATTEMPT]
    if RESUMABLE_LEAD_MIN:
        env.append('KAOS_RESUMABLE=1')
    if RESUME:
        env += ['KAOS_RESUME_REF=' + RESUME[0], 'KAOS_RESUME_PREFIX=' + RESUME[1]]
    # Same outputs location + run id as the in-cluster copy (outputs-<app>).
    # Only when set: step code reads os.environ.get(..., default), so an empty
    # value would override its own default.
    env += [k + '=' + os.environ[k] for k in
            ('CHECKPOINT_BUCKET', 'CHECKPOINT_PREFIX', 'KUBECORE_RUN_ID', 'KUBECORE_WORKFLOW_NAME',
             'KAOS_LIB_SUPPORT')
            if os.environ.get(k)]
    global WALLET, WALLET_EXP
    wallet = WALLET = mint_wallet()
    WALLET_EXP = wallet_exp(wallet)
    if wallet:
        # Public endpoints only, short-lived bearer only (T-03). MLflow's
        # client honors MLFLOW_TRACKING_TOKEN natively; the stage-in and any
        # in-step lakeFS API calls ride the same bearer through oauth2-proxy.
        mlflow_url = os.environ.get('MLFLOW_EXTERNAL_URL') or ''
        lakefs_url = os.environ.get('LAKEFS_EXTERNAL_URL') or ''
        if mlflow_url:
            env += ['MLFLOW_TRACKING_URI=' + mlflow_url,
                    'MLFLOW_TRACKING_TOKEN=' + wallet]
        if lakefs_url:
            env += ['LAKEFS_ENDPOINT=' + lakefs_url,
                    'LAKEFS_BEARER_TOKEN=' + wallet,
                    'DATASET_REPO=' + dataset_coords()[0],
                    'DATASET_REF=' + dataset_coords()[1],
                    'DATASET_COMMIT=' + (PINNED or pinned_commit()),
                    'OUTPUTS_REPO=' + (os.environ.get('OUTPUTS_REPO') or ''),
                    'OUTPUTS_REF=' + (os.environ.get('OUTPUTS_REF') or ''),
                    'STAGEIN_B64='
                    + base64.b64encode(STAGEIN.encode()).decode(),
                    'STAGEOUT_B64='
                    + base64.b64encode(STAGEOUT.encode()).decode()]
            if RESUMABLE_LEAD_MIN:
                env += ['CKPTOUT_B64=' + base64.b64encode(CKPTOUT.encode()).decode(),
                        'CKPTIN_B64=' + base64.b64encode(CKPTIN.encode()).decode()]
    commit = pinned_commit()
    if commit:
        env.append('KAOS_COMMIT=' + commit)   # fail() keeps the dataset lease
    step_limit = int(os.environ.get('SLURM_TIME_LIMIT') or 240)
    job_limit = step_limit
    hosting = SHARING and int(HPC.get('gpus') or 0) > 0
    if hosting:
        # F-03: the batch step becomes the host (slot manager); one slot per GPU.
        env += ['KAOS_SLOTS_B64=' + base64.b64encode(SLOTS.encode()).decode(),
                'KAOS_SCOPE=' + SCOPE, 'KAOS_SCR=' + ident['scratch'],
                'KAOS_STEP_LIMIT_MIN=%d' % step_limit]
        # A host can only take steps that end before its own time limit, so with equal
        # limits nothing would ever fit: the job asks Slurm for twice its step's time,
        # capped by the class's maximum (partition/QOS). Every step still runs with its
        # own limit, and the host releases the node 2 minutes after its last step.
        # No known maximum: no padding (a request above the QOS cap would pend forever).
        cap = int(HPC.get('maxTimeLimitMinutes') or 0)
        if cap:
            job_limit = max(step_limit, min(2 * step_limit, cap))
        if WALLET_EXP:
            env.append('KAOS_TOKEN_EXP=%d' % WALLET_EXP)   # the host's fit rule (D-07)
    if SHARING:
        batch, env = inputs_in_script(batch, env)
    body = {'job': {'name': jobname, 'partition': HPC['partition'],
                    'account': ident['account'],
                    'qos': HPC.get('qos') or 'default',
                    'time_limit': job_limit,
                    'current_working_directory': ident['home'],
                    'environment': env, 'tasks': 1, 'nodes': '1'},
            'script': batch}
    if commit:
        # PRD-1541 D-06: the stager never evicts a commit a queued or running
        # job names here (squeue %k).
        body['job']['comment'] = 'kaos-commit=' + commit
    if SHARING and int(HPC.get('gpus') or 0) > 0:
        # PRD-1609 offer window (PRD-HPC-1461 N-12): a sharing job starts OFFER_S late,
        # so a running host of the same scope can take it even when free nodes would
        # start it at once (a quiet site packed nothing: e2e 56c7480b). Slurm makes it
        # eligible by itself afterwards: nothing has to release it, so there is no race
        # beyond the one take() already handles (hold, then check it is still pending).
        # Live 2026-11-05 (job 5422046): BeginTime for 45 s, then it started alone.
        body['job']['begin_time'] = {'set': True, 'number': int(time.time()) + OFFER_S}
    if not hosting:
        # PRD-HPC-1461 D-37: requeue lets the site put a pre-empted job back in the
        # queue with its ID and place (users cannot requeue their own jobs on MeluXina).
        body['job']['requeue'] = True
    if RESUMABLE_LEAD_MIN:
        # D-44 (amended 2026-11-05): only a resumable step is told to save. USR1 goes to
        # the batch shell its lead before the wall time (the render keeps the lead shorter
        # than the wall time), which passes it to the step. A resumable step never shares
        # a node, so this job's limit is its step's.
        body['job'].update({'kill_warning_signal': 'USR1', 'kill_warning_flags': ['BATCH_JOB'],
                            'kill_warning_delay': {'set': True, 'number': RESUMABLE_LEAD_MIN * 60}})
    req = urllib.request.Request(API + '/job/submit',
                                 data=json.dumps(body).encode(),
                                 headers=hdrs(), method='POST')
    try:
        resp = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        print('job submit refused:', submit_refusal(e), flush=True)
        sys.exit(1)
    j = resp.get('job_id')
    print('submitted job', j, 'errors:', resp.get('errors'), flush=True)
    if not j:
        sys.exit(1)
    # A resubmit replaces the site job of the same attempt: the attempt does not end.
    report(siteJobID=str(j), state='PENDING')
    return j


def submit_refusal(e):
    """slurmrestd refuses a job with an HTTP error whose body names why
    (errors/warnings: an account, partition or QOS it rejects, a time limit
    above the QOS); without it the step dies on a bare 'HTTP Error 500'."""
    try:
        why = json.loads(e.read().decode(errors='replace') or '{}')
    except Exception:
        why = {}
    if not isinstance(why, dict):
        why = {}
    return 'HTTP %s %s' % (e.code, {k: why.get(k) for k in ('errors', 'warnings')
                                     if why.get(k)} or '(no reason in the body)')


def cancel(j):
    try:
        urllib.request.urlopen(urllib.request.Request(
            API + '/job/' + str(j), headers=hdrs(), method='DELETE'), timeout=30)
        print('cancelled job', j, flush=True)
    except Exception as e:
        print('cancel failed:', e, flush=True)


# PRD-HPC-1461 F-26 / D-34, phase 0 "observe and admit": with the pool's HPC controller on, every
# attempt of this step is an HPCArgoWorkflowJob in this namespace. The runner submits an attempt only
# after the controller admitted it and booked it against the project's share, and reports the site
# job to it (status.run) so the controller settles each attempt and decides a continuation. Off
# (the default): nothing here runs and the step behaves as before. On but unusable (no controller
# on the pool, no permission): the step fails; it never submits around the admission.
CONTROLLER = os.environ.get('HPC_CONTROLLER') == 'on'
K8S_SA = '/var/run/secrets/kubernetes.io/serviceaccount'
RECORD_ACTIVE = ('Admitted', 'Running')
RECORD_TERMINAL = ('Succeeded', 'Failed', 'Cancelled', 'Refused')
RUN_FIELDS = ('attempt', 'siteJobID', 'state', 'exitCode', 'startTime', 'endTime', 'terminal',
              'hostSiteJobID', 'slot', 'checkpointRef')


def k8s(method, path, body=None, ctype='application/json'):
    import ssl
    tok = open(K8S_SA + '/token').read().strip()          # re-read: projected tokens rotate
    req = urllib.request.Request(
        'https://kubernetes.default.svc' + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + tok, 'Content-Type': ctype, 'Accept': 'application/json'})
    ctx = ssl.create_default_context(cafile=K8S_SA + '/ca.crt')
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return json.load(r)


def record_name():
    """One record per step of a workflow run: deterministic, so a retried waiter finds it."""
    name = re.sub('[^a-z0-9-]+', '-', ('%s-%s' % (os.environ.get('KUBECORE_WORKFLOW_NAME') or '',
                                                  os.environ['STEP_NAME'])).lower()).strip('-')
    if len(name) > 63:
        name = name[:54].rstrip('-') + '-' + hashlib.sha256(name.encode()).hexdigest()[:8]
    return name


def record_path(sub=''):
    ns = open(K8S_SA + '/namespace').read().strip()
    return '/apis/hpc.kaos.io/v1alpha1/namespaces/%s/hpcargoworkflowjobs/%s%s' % (ns, record_name(), sub)


def record_spec():
    spec = {'class': os.environ.get('HPC_CLASS') or '', 'image': img,
            'command': json.loads(os.environ.get('STEP_COMMAND') or '[]', strict=False),
            'wallTimeMinutes': int(os.environ.get('SLURM_TIME_LIMIT') or 240), 'nodes': 1,
            'outputs': [n for n in (os.environ.get('STEP_OUTPUTS') or '').split(',') if n]}
    if os.environ.get('DATASET'):
        spec['datasetRef'] = '%s@%s' % dataset_coords()
    if RESUMABLE_LEAD_MIN:
        spec['resumable'] = {'leadMinutes': RESUMABLE_LEAD_MIN, 'maxContinuations': MAX_CONTINUATIONS}
    return spec


def record_unusable(e):
    code = getattr(e, 'code', None)
    why = {404: 'the pool has no HPC controller (no hpcargoworkflowjobs.hpc.kaos.io)',
           403: 'this step may not create its HPC job record'}.get(code)
    if why:
        print('HPC controller is on for this project, but %s; not submitting around its admission'
              ' (PRD-HPC-1461 D-34)' % why, flush=True)
        sys.exit(1)


def ensure_record():
    """Create this step's record (owned by its Workflow) or, on a retried waiter, read the existing one."""
    body = {'apiVersion': 'hpc.kaos.io/v1alpha1', 'kind': 'HPCArgoWorkflowJob',
            'metadata': {'name': record_name(),
                         'labels': {'workflows.argoproj.io/workflow': os.environ.get('KUBECORE_WORKFLOW_NAME') or '',
                                    'hpc.kaos.io/step': os.environ['STEP_NAME'][:63]},
                         'ownerReferences': [{'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Workflow',
                                              'name': os.environ.get('KUBECORE_WORKFLOW_NAME') or '',
                                              'uid': os.environ['WF_UID']}]},
            'spec': record_spec()}
    for n in range(30):
        try:
            return k8s('POST', record_path()[:record_path().rindex('/')], body)
        except urllib.error.HTTPError as e:
            if e.code == 409:
                try:
                    return k8s('GET', record_path())
                except urllib.error.HTTPError as g:
                    e = g
            record_unusable(e)
            print('HPC job record: HTTP %s, retrying' % e.code, flush=True)
        except Exception as e:
            print('HPC job record: %s, retrying' % e, flush=True)
        time.sleep(10)
    print('HPC job record: the API server did not answer for 5 minutes', flush=True)
    sys.exit(1)


def await_admission(attempt):
    """Block until the controller admits this attempt and books it. Its refusal, or the record ending
    (for example a continuation it declined), ends the step with the controller's reason."""
    last = None
    while True:
        try:
            st = k8s('GET', record_path()).get('status') or {}
        except Exception as e:
            print('HPC job record unreadable (%s), asking again' % e, flush=True)
            time.sleep(10)
            continue
        phase = st.get('phase') or 'Pending'
        if int(st.get('attempt') or 1) == attempt and phase in RECORD_ACTIVE:
            b = st.get('booking') or {}
            print('admitted: attempt %d, %s node-minutes booked on %s' % (
                attempt, b.get('nodeMinutes', '?'), b.get('siteName', '?')), flush=True)
            return st
        if phase in RECORD_TERMINAL:
            print('not admitted: %s %s: %s' % (phase, st.get('reason') or '', st.get('message') or ''), flush=True)
            sys.exit(1)
        if (phase, st.get('reason')) != last:
            print('waiting for the HPC controller: %s %s %s' % (
                phase, st.get('reason') or '', st.get('message') or ''), flush=True)
            last = (phase, st.get('reason'))
        time.sleep(5)


def site_time(job, key):
    t = ((job.get('time') or {}).get(key))
    t = t.get('number') if isinstance(t, dict) else t
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t)) if t else None


def report(must=False, **run):
    """status.run of this attempt, every field written (a merge patch would keep an earlier attempt's
    exit code or checkpoint). must: retry until it lands; the controller settles from it."""
    if not CONTROLLER:
        return
    run['attempt'] = ATTEMPT
    body = {'status': {'run': {k: run.get(k) for k in RUN_FIELDS}}}
    for n in range(60 if must else 1):
        try:
            k8s('PATCH', record_path('/status'), body, 'application/merge-patch+json')
            return
        except Exception as e:
            print('HPC job record: report failed (%s)%s' % (e, ', retrying' if must else ''), flush=True)
            if must:
                time.sleep(10)
    if must:
        print('HPC job record: the end of the site job could not be reported', flush=True)
        sys.exit(1)


def checkpoint_uri(ckpt):
    return 'lakefs://%s/%s/%s' % (os.environ.get('OUTPUTS_REPO') or '', ckpt[0], ckpt[1])


def resume_of(uri):
    """(commit, path) from a checkpoint URI the runner reported, or None."""
    m = re.fullmatch(r'lakefs://[^/]+/([0-9a-f]{40,64})/(\S+/)', uri or '')
    return (m.group(1), m.group(2)) if m else None


def on_term(signum, frame):
    # Argo sends TERM on deadline/stop. A PENDING job never started — cancel
    # it so it does not run unobserved hours later (live job 5143859 did
    # exactly that: waiter killed at the deadline mid-queue, job ran at
    # 20:0xZ with nobody watching and burned a failed pull). A RUNNING job
    # is deliberately left to finish.
    try:
        j = (get(API + '/job/' + str(jid)).get('jobs') or [{}])[0]
        if 'PENDING' in (j.get('job_state') or []):
            cancel(jid)
            report(siteJobID=str(jid), state='CANCELLED', terminal=True)
    except Exception:
        pass
    sys.exit(143)


signal.signal(signal.SIGTERM, on_term)

START_CONTINUATIONS = 0
if CONTROLLER:
    st = ensure_record().get('status') or {}
    # A retried waiter continues where the record is: its attempt, continuations and resume point.
    ATTEMPT = max(int(st.get('attempt') or 1), 1)
    START_CONTINUATIONS = int(st.get('continuations') or 0)
    RESUME = resume_of((st.get('resume') or {}).get('checkpointRef'))
    print('HPC job record %s: attempt %d' % (record_name(), ATTEMPT), flush=True)
jid = find_active()
if jid is not None:
    print('adopting existing job', jid, flush=True)
else:
    if CONTROLLER:
        await_admission(ATTEMPT)
    jid = submit()

open('/tmp/slurm-job-id', 'w').write(str(jid))
OUTPUT_NAMES = [n for n in os.environ.get('STEP_OUTPUTS', '').split(',') if n]
os.makedirs('/tmp/outputs', exist_ok=True)
for n in OUTPUT_NAMES:
    open('/tmp/outputs/%s.json' % n, 'w').write('{}')


def fetch_outputs():
    """F-05: pull the step's staged-out outputs back into the twin."""
    base = (os.environ.get('LAKEFS_EXTERNAL_URL') or '').rstrip('/')
    repo = os.environ.get('OUTPUTS_REPO') or ''
    if not (OUTPUT_NAMES and base and repo and WALLET):
        return
    branch = 'hpc-%s-%s' % (os.environ.get('WF_UID', ''), os.environ.get('STEP_NAME', ''))
    for n in OUTPUT_NAMES:
        q = urllib.parse.urlencode({'path': 'hpc-outputs/%s/%s/%s.json' % (
            os.environ.get('WF_UID', ''), os.environ.get('STEP_NAME', ''), n)})
        try:
            data = urllib.request.urlopen(urllib.request.Request(
                base + '/api/v1/repositories/%s/refs/%s/objects?%s' % (repo, branch, q),
                headers={'Authorization': 'Bearer ' + WALLET}), timeout=60).read()
            open('/tmp/outputs/%s.json' % n, 'wb').write(data)
            print('output', n, ':', len(data), 'bytes', flush=True)
        except Exception as e:
            print('output', n, 'not staged out (default {}):', e, flush=True)
    try:   # the hand-off branch has done its job
        urllib.request.urlopen(urllib.request.Request(
            base + '/api/v1/repositories/%s/branches/%s' % (repo, branch), method='DELETE',
            headers={'Authorization': 'Bearer ' + WALLET}), timeout=60).read()
    except Exception as e:
        print('hand-off branch', branch, 'not deleted:', e, flush=True)


TERMINAL = ('COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'NODE_FAIL',
            'PREEMPTED', 'OUT_OF_MEMORY')
# The registry pull token (GCE metadata, 1 h) is minted at submit time and
# cannot be refreshed inside a queued job, so every queue wait longer than an
# hour costs one failed pull (exit 231) and a resubmission. Bounded, not
# once: a second long wait after the first resubmit must not strand the run.
PULL_RESUBMITS = 3
resubmits = 0
# Continuations so far (D-44); a retried waiter starts from its record's count.
continuations = START_CONTINUATIONS
reported = None   # the last (state, host, slot) reported to the HPC job record


def checkpoint_path(attempt):
    return 'hpc-checkpoints/%s/%s/attempt-%d/' % (os.environ.get('WF_UID', ''),
                                                  os.environ.get('STEP_NAME', ''), attempt)


def checkpoint_of(job, jid):
    """(commit, path) of the checkpoint this job staged out before it exited 85, or None.
    The batch script writes them into the job comment after the upload committed; accounting
    may lag that, so slurmctld is asked too, a few times. Only this attempt's path counts."""
    for n in range(4):
        texts = [comment_of(job)]
        try:
            texts.append(comment_of((get(API + '/job/' + str(jid)).get('jobs') or [{}])[0]))
        except Exception:
            pass
        for c in texts:
            m = dict(re.findall(r'(?:^|\s)(kaos-ckpt|kaos-ckpt-path)=(\S+)', c))
            if (re.fullmatch('[0-9a-f]{40,64}', m.get('kaos-ckpt', ''))
                    and m.get('kaos-ckpt-path') == checkpoint_path(ATTEMPT)):
                return m['kaos-ckpt'], m['kaos-ckpt-path']
        if n < 3:
            time.sleep(20)
            try:
                job = (get(SDB + '/job/' + str(jid)).get('jobs') or [{}])[0]
            except Exception:
                pass
    return None


def checkpoint_committed(commit):
    """A4: the checkpoint commit exists in the outputs repository. Asked a few times: an
    unreachable lakeFS is not a missing checkpoint, but it never lets the step continue either."""
    base = (os.environ.get('LAKEFS_EXTERNAL_URL') or '').rstrip('/')
    repo = os.environ.get('OUTPUTS_REPO') or ''
    if not (base and repo and WALLET):
        return False
    for n in range(4):
        try:
            c = json.load(urllib.request.urlopen(urllib.request.Request(
                base + '/api/v1/repositories/%s/commits/%s' % (repo, commit),
                headers={'Authorization': 'Bearer ' + WALLET}), timeout=60))
            return c.get('id') == commit
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            print('checkpoint commit check:', e, flush=True)
        except Exception as e:
            print('checkpoint commit check:', e, flush=True)
        time.sleep(15 * (n + 1))
    return False
# Why Slurm holds a queued job (Priority, Resources, AssocGrpGRESMinutes = the
# allocation's GPU minutes are spent, ...): only slurmctld knows it, the
# accounting record polled below does not. Printed when it changes, so a run
# that never left the queue says why (kaos e2e 2026-10-26: two jobs PENDING
# for the whole 2.5 h budget, reason unknown).
pending_reason = None
hosted = None   # PRD-1609: the host that took this job, as last printed
# PRD-1609: how often this run started over because its host died with it.
LOST_HOST_RESUBMITS = 3
lost_hosts = 0
HOST_ALIVE = ('PENDING', 'RUNNING', 'SUSPENDED', 'COMPLETING')


def host_gone(host):
    """True only when accounting says the host job ended: an unreadable record
    is not a death (the host keeps running; the next poll asks again)."""
    try:
        h = (get(SDB + '/job/' + str(host)).get('jobs') or [{}])[0]
    except Exception:
        return False
    hst = (h.get('state') or {}).get('current') or []
    return bool(hst) and not any(x in HOST_ALIVE for x in hst)


while True:
    time.sleep(30)
    try:
        job = (get(SDB + '/job/' + str(jid)).get('jobs') or [{}])[0]
        st = (job.get('state') or {}).get('current') or []
        print('state:', st, flush=True)
        share = share_state(comment_of(job))
        now = (','.join(st), share.get('host'), share.get('slot'))
        if CONTROLLER and now != reported and not any(x in TERMINAL for x in st):
            report(siteJobID=str(jid), state=now[0], startTime=site_time(job, 'start'),
                   hostSiteJobID=share.get('host'),
                   slot=int(share['slot']) if (share.get('slot') or '').isdigit() else None)
            reported = now
        if 'PENDING' in st:
            try:
                live = (get(API + '/job/' + str(jid)).get('jobs') or [{}])[0]
                reason = live.get('state_reason') or ''
                # The live comment: accounting may lag a host's update.
                share = share_state(comment_of(live)) or share
            except Exception:
                reason = pending_reason or ''
            if reason != pending_reason:
                print('pending reason:', reason, flush=True)
                pending_reason = reason
            if share.get('kaos-state') == 'taken' and share != hosted:
                print('running on a shared node: host job', share.get('host'),
                      'slot', share.get('slot'), flush=True)
                hosted = share
        elif 'RUNNING' in st and SHARING:
            # PRD-1609 F-03: a host keeps its node while its guests run; its own
            # step's result is in its comment as soon as that step ends.
            try:
                live = (get(API + '/job/' + str(jid)).get('jobs') or [{}])[0]
                share = share_state(comment_of(live)) or share
            except Exception:
                pass
        if ('PENDING' in st and share.get('kaos-state') == 'taken' and share.get('host')
                and lost_hosts < LOST_HOST_RESUBMITS and host_gone(share['host'])):
            # PRD-1609: the host died without handing this job back (node failure,
            # crash): it stays held forever. Start over as a new job — the same
            # cancel + submit as the wallet resubmit, so no new Slurm call.
            lost_hosts += 1
            print('host job', share['host'], 'is gone with this step - resubmitting'
                  ' (%d/%d)' % (lost_hosts, LOST_HOST_RESUBMITS), flush=True)
            cancel(jid)
            jid = submit()
            open('/tmp/slurm-job-id', 'w').write(str(jid))
            hosted = None
            continue
        # A job a host took stays queued (held) while its step runs: never
        # resubmit it. The host checked its token outlives the step (D-07).
        if ('PENDING' in st and share.get('kaos-state') != 'taken' and WALLET_EXP
                and time.time() > WALLET_EXP - WALLET_MARGIN_S):
            print('wallet expires within', WALLET_MARGIN_S // 60,
                  'min and the job is still queued - resubmitting with a'
                  ' fresh wallet (queue position is lost, credentials are'
                  ' not)', flush=True)
            cancel(jid)
            jid = submit()
            open('/tmp/slurm-job-id', 'w').write(str(jid))
            continue
        if any(x in TERMINAL for x in st) or ('RUNNING' in st and share.get('kaos-state') == 'done'):
            rc = ((job.get('exit_code') or {}).get('return_code')
                  or {}).get('number')
            print('terminal:', st, 'exit:', rc, flush=True)
            print('job comment:', job.get('comment'), flush=True)
            if share.get('kaos-state') == 'done':
                # PRD-1609 D-04: a host ran this step on a shared node and then
                # cancelled this job; the step's result is in the comment.
                rc = int(share['rc']) if share.get('rc', '').isdigit() else 1
                print('ran on a shared node: host job', share.get('host'),
                      'exit:', share.get('rc'), flush=True)
                st = ['COMPLETED'] if rc == 0 else ['FAILED']
            if 'FAILED' in st and rc == 231 and resubmits < PULL_RESUBMITS:
                # A cache-missing pull after a LONG queue wait runs with the
                # registry token minted at submit time — GCP tokens live 1h,
                # so it can be stale (live job 5143859: 3.5h queue -> 231;
                # 5150371: 65 min queue -> 231). Resubmitting mints
                # everything fresh; queue age is lost only after an actual
                # failure.
                resubmits += 1
                print('pull failed - resubmitting with fresh credentials'
                      ' (%d/%d)' % (resubmits, PULL_RESUBMITS), flush=True)
                jid = submit()
                open('/tmp/slurm-job-id', 'w').write(str(jid))
                continue
            if rc == CHECKPOINT_EXIT and not any(x in st for x in ('COMPLETED', 'CANCELLED')):
                # D-44 (amended 2026-11-05), A2/A4: continue only a resumable step, only from a
                # checkpoint that reached the outputs repository, and at most MAX_CONTINUATIONS times.
                ckpt = checkpoint_of(job, jid) if RESUMABLE_LEAD_MIN else None
                if not RESUMABLE_LEAD_MIN:
                    why = 'the step exited 85, but it is not declared resumable'
                elif not ckpt:
                    why = ('its checkpoint did not reach the outputs repository before the job ended'
                           ' (a longer resumable= lead leaves the upload more time)')
                elif not checkpoint_committed(ckpt[0]):
                    why = 'its checkpoint commit %s is not in the outputs repository' % ckpt[0][:12]
                elif continuations >= MAX_CONTINUATIONS:
                    why = 'the step was continued %d times already' % MAX_CONTINUATIONS
                else:
                    why = ''
                if why:
                    print('not continuing the step:', why, flush=True)
                    report(must=True, siteJobID=str(jid), state=','.join(st), exitCode=rc,
                           startTime=site_time(job, 'start'), endTime=site_time(job, 'end'), terminal=True,
                           checkpointRef=checkpoint_uri(ckpt) if ckpt else None)
                    sys.exit(1)
                report(must=True, siteJobID=str(jid), state=','.join(st), exitCode=rc,
                       startTime=site_time(job, 'start'), endTime=site_time(job, 'end'), terminal=True,
                       checkpointRef=checkpoint_uri(ckpt))
                continuations += 1
                ATTEMPT += 1
                RESUME = ckpt
                print('the step saved its checkpoint (%s) before its wall time - continuing it in a'
                      ' new job (%d/%d)' % (ckpt[0][:12], continuations, MAX_CONTINUATIONS), flush=True)
                if CONTROLLER:
                    await_admission(ATTEMPT)   # re-booked like a new step (A4); it may decline
                reported = None
                jid = submit()
                open('/tmp/slurm-job-id', 'w').write(str(jid))
                continue
            if 'COMPLETED' in st:
                fetch_outputs()
            report(must=True, siteJobID=str(jid), state=','.join(st), exitCode=rc,
                   startTime=site_time(job, 'start'), endTime=site_time(job, 'end'), terminal=True)
            sys.exit(0 if ('COMPLETED' in st and rc in (0, None)) else 1)
    except SystemExit:
        raise
    except Exception as e:
        print('poll error (transient):', e, flush=True)
'''


_SUBST_TAG = re.compile(
    r"\{\{\s*((?:workflow\.parameters|tasks)\.[A-Za-z0-9_.-]+)\s*\}\}")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _tag_expr(path: str) -> str:
    """Convert a dotted Argo tag path to expression syntax, using bracket
    access for segments that are not bare identifiers (task and param names
    routinely carry hyphens: tasks.compose-and-validate.outputs...)."""
    segs = path.split(".")
    out = segs[0]
    for s in segs[1:]:
        out += "." + s if _IDENT.match(s) else "['%s']" % s
    return out


_TASK_OUTPUT = re.compile(r"^tasks\.([A-Za-z0-9_-]+)\.outputs\.parameters\.([A-Za-z0-9_.-]+)$")


def _pair_expr(task: str, param: str, provider: str) -> str:
    """Expression for a routed upstream's output: exactly one twin ran, the
    other is Skipped and its outputs resolve to their defaults — pick the
    twin that ran."""
    return ("tasks['%s'].status == 'Skipped' ? tasks['%s-%s'].outputs."
            "parameters['%s'] : tasks['%s'].outputs.parameters['%s']"
            % (task, task, provider, param, task, param))


def _cmd_json(cmd: list, routed=(), provider: str = "") -> str:
    """Render the step-command as a JSON array that STAYS valid JSON after
    Argo's parameter substitution.

    References to a routed upstream's outputs are pair-aware (`_pair_expr`):
    a twin whose upstream ALSO ran on HPC must read the upstream twin, not
    the Skipped in-cluster task (observed at run time: a GPU step on
    MeluXina got --training-result "" and fine-tuned the base weights).

    A naive json.dumps breaks at run time (observed at run time): Argo
    substitutes {{workflow.parameters.X}} / {{tasks.X.outputs.parameters.Y}}
    INSIDE the already-serialized string, and a multi-line value (the
    compose-and-validate params.yaml output is a whole YAML doc) lands raw
    newlines/quotes inside a JSON string — the submit pod's json.loads dies
    on 'invalid control character'. Fix: tokens carrying substitutable tags
    are emitted as {{=toJson(...)}} expressions, so Argo itself JSON-escapes
    the substituted value; literal tokens stay json.dumps'd. Mixed tokens
    rebuild the full string inside the expression via single-quoted
    concatenation."""
    parts = []
    for tok in cmd:
        if not _SUBST_TAG.search(tok):
            parts.append(json.dumps(tok))
            continue
        exprs, pos = [], 0
        for m in _SUBST_TAG.finditer(tok):
            if m.start() > pos:
                exprs.append("'%s'" % tok[pos:m.start()].replace("\\", "\\\\").replace("'", "\\'"))
            ref = _TASK_OUTPUT.match(m.group(1))
            if ref and ref.group(1) in routed:
                exprs.append(("(%s)", _pair_expr(ref.group(1), ref.group(2), provider)))
            else:
                exprs.append(_tag_expr(m.group(1)))
            pos = m.end()
        if pos < len(tok):
            exprs.append("'%s'" % tok[pos:].replace("\\", "\\\\").replace("'", "\\'"))
        # a ternary needs parentheses only when concatenated with literals
        exprs = [(e[0] % e[1] if len(exprs) > 1 else e[1]) if isinstance(e, tuple) else e
                 for e in exprs]
        parts.append("{{=toJson(%s)}}" % " + ".join(exprs))
    return "[" + ", ".join(parts) + "]"


DEFAULT_TIME_LIMIT_MINUTES = 240
# Argo budget on top of the Slurm limit: the twin pod also waits in the
# MeluXina queue (evening waits run to hours), builds the SIF and stages the
# dataset in before the job's own clock starts. If the twin's deadline fires
# first, on_term leaves a RUNNING job to finish unobserved — so the deadline
# must comfortably exceed queue + prep + time limit.
QUEUE_ALLOWANCE_MINUTES = 480
# PRD-HPC-1461 D-44: a step that saves on the stop signal continues in a new job,
# at most this many times (MAX_CONTINUATIONS in the waiter). Each job may queue,
# prepare and run again, so the waiter's deadline covers all of them.
HPC_MAX_CONTINUATIONS = 5
HPC_ANNOTATION = "platform.kubecore.io/hpc"
# step(resumable=...): how long before its wall time the step is told to save (D-44 as amended
# 2026-11-05). Only resumable steps get the signal and continue.
HPC_RESUMABLE_ANNOTATION = "platform.kubecore.io/hpc-resumable"
# How the kubelet words a waiter pod lost with its node: Argo marks such a pod
# Failed (a pod with a status message is never an Error), so OnError alone
# never retries a Spot preemption or a node-pressure eviction.
POD_LOSS_MESSAGES = ("imminent node shutdown|node is shutting down|node is draining"
                     "|The node was low on resource|The node had condition"
                     "|Pod was rejected|Evicted|evicted|pod deleted|Pod was deleted")
POD_LOSS_RETRY = ("lastRetry.status == 'Error' or lastRetry.message matches '.*(%s).*'"
                  % POD_LOSS_MESSAGES)


def sharing_env(ctx: dict) -> list:
    """PRD-1609 node sharing, as the operator published it in pipeline-context hpc.*
    (sharing: on, scope: the project's hash). Nothing is added unless it is on, so a
    project without sharing renders the waiter exactly as before."""
    hpc = ctx.get("hpc") or {}
    # "on" as the operator renders it (quoted); a YAML 1.1 reader turns a bare on into True.
    if hpc.get("sharing") not in ("on", True) or not hpc.get("scope"):
        return []
    return [{"name": "HPC_SHARING", "value": "on"},
            {"name": "HPC_SCOPE", "value": str(hpc["scope"])}]


def controller_env(ctx: dict) -> list:
    """PRD-HPC-1461 D-34 phase 0: the operator publishes hpc.controller "on" in the pipeline context
    once the pool's HPC controller serves the project; the waiter then submits only after it admits.
    Absent: nothing is added and the waiter renders exactly as before."""
    if (ctx.get("hpc") or {}).get("controller") not in ("on", True):
        return []
    return [{"name": "HPC_CONTROLLER", "value": "on"}]


def pull_env(ctx: dict) -> list:
    """The read-only image-pull GSA (<org>-hpc-pull) the operator publishes as hpc.pullServiceAccount;
    the waiter mints the job's 12 h registry token as it. Absent: nothing is added and the waiter
    keeps pulling with its own 1 h token."""
    sa = (ctx.get("hpc") or {}).get("pullServiceAccount")
    return [{"name": "HPC_PULL_SA", "value": str(sa)}] if sa else []


def parse_time_limit(value) -> int:
    """'90' / '90m' -> 90 minutes, '12h' -> 720. Raises ValueError otherwise."""
    text = str(value).strip()
    m = re.match(r"^([0-9]+)([mh]?)$", text)
    if not m or int(m.group(1)) == 0:
        raise ValueError(
            "%s=%r: expected minutes or hours like '90m', '12h' or '720'"
            % (HPC_ANNOTATION, value))
    minutes = int(m.group(1))
    return minutes * 60 if m.group(2) == "h" else minutes


def step_resumable_lead(step: dict) -> int:
    """Minutes before the wall time a resumable step gets the stop signal; 0 when it is not resumable."""
    raw = ((step.get("metadata") or {}).get("annotations") or {}).get(HPC_RESUMABLE_ANNOTATION)
    return parse_time_limit(raw) if raw not in (None, "") else 0


def step_time_limit(step: dict) -> int:
    """Slurm wall-clock minutes for a routed step (annotation or default)."""
    raw = ((step.get("metadata") or {}).get("annotations") or {}).get(HPC_ANNOTATION)
    return parse_time_limit(raw) if raw not in (None, "") else DEFAULT_TIME_LIMIT_MINUTES


HPC_CLASS_PREFIX_FMT = "%s-"  # class names are provider-prefixed: meluxina-gpu


def hpc_classes(ctx: dict) -> list:
    """The HPC compute classes the account can use, from the pipeline
    context (k8smlapp composition, gated on hpcReady). Each entry:
    {name, tier, partition, qos, gpus, cpus, memoryGiB, description}."""
    hpc = ctx.get("hpc") or {}
    if not hpc.get("enabled"):
        return []
    return [dict(c) for c in (hpc.get("classes") or []) if c.get("name")]


def _when_expr(when: str) -> str:
    """Translate a simple-tag `when` ({{workflow.parameters.X}} == Y / != Y)
    into an Argo expression; an expression `when` ({{=...}}) is passed
    through. Anything else fails the render loudly: a silently dropped gate
    would run a step the author disabled."""
    w = (when or "").strip()
    if not w:
        return ""
    if w.startswith("{{=") and w.endswith("}}"):
        return w[3:-2].strip()
    m = re.match(r"^\{\{\s*workflow\.parameters\.([A-Za-z0-9_.-]+)\s*\}\}\s*(==|!=)\s*(\S+)$", w)
    if not m:
        raise ValueError(
            "meluxina: cannot combine the step's when %r with the HPC class gate — "
            "use {{workflow.parameters.X}} == Y / != Y or an {{= expression }}" % when)
    param, op, value = m.groups()
    value = value.strip("'\"")
    return "workflow.parameters['%s'] %s '%s'" % (param, op, value)


def enhance_hpc(spec: dict, ctx: dict, steps: list, gpu_step_names: set) -> None:
    """Per-step HPC placement. Every step's
    {step}-class dropdown carries the HPC classes (enhance_class_param);
    here each un-pinned step gets a Slurm twin, and the pair is gated on
    the chosen class: in-cluster when the class is not HPC, twin when it is.
    A step's own `when` is preserved on both."""
    classes = hpc_classes(ctx)
    if not classes:
        return
    provider = (ctx.get("hpc") or {}).get("provider", "meluxina")
    prefix = HPC_CLASS_PREFIX_FMT % provider
    by_class = {c["name"]: c for c in classes}

    # The global `target` switch is gone: placement is per step.
    parameters = spec["arguments"]["parameters"]
    parameters[:] = [p for p in parameters if p.get("name") != "target"]

    entry = spec.get("entrypoint")
    dag_tpl = next((t for t in spec.get("templates", [])
                    if t.get("name") == entry and "dag" in t), None)
    if dag_tpl is None:
        return
    tasks = dag_tpl["dag"]["tasks"]
    by_tpl = {s["name"]: s for s in steps}

    def _routable(task):
        step = by_tpl.get(task.get("template"))
        annots = ((step or {}).get("metadata") or {}).get("annotations") or {}
        # pinned to one in-cluster class: no HPC twin
        return step is not None and "platform.kubecore.io/compute-class" not in annots

    routable = {t["name"] for t in tasks if _routable(t)}
    routed = []
    outputs_union: set = set()
    for task in list(tasks):
        if task["name"] not in routable:
            continue
        step = by_tpl[task["template"]]
        class_param = "workflow.parameters['%s-class']" % step["name"]
        own = _when_expr(task.get("when", ""))
        hpc_gate = "hasPrefix(%s, '%s')" % (class_param, prefix)
        task["when"] = "{{=%s!%s}}" % ("(%s) && " % own if own else "", hpc_gate)
        twin_when = "{{=%s%s}}" % ("(%s) && " % own if own else "", hpc_gate)
        container = step.get("container") or {}
        argmap = {p.get("name"): str(p.get("value", ""))
                  for p in ((task.get("arguments") or {}).get("parameters")
                            or [])}
        cmd = [re.sub(r"\{\{\s*inputs\.parameters\.([A-Za-z0-9_.-]+)\s*\}\}",
                      lambda m: argmap.get(m.group(1), ""), tok)
               for tok in ((container.get("command") or [])
                           + (container.get("args") or []))]
        cmd = [t for t in cmd
               if t and "{{inputs." not in t and "{{item" not in t]
        minutes = step_time_limit(step)
        lead = step_resumable_lead(step)
        if lead >= minutes:
            raise ValueError("step %s: resumable lead %d min is not shorter than its wall time %d min"
                             % (step["name"], lead, minutes))
        # A resumable step may run (1 + HPC_MAX_CONTINUATIONS) jobs, each queuing, preparing and
        # running again; any other step runs one, so its waiter's deadline stays one job's.
        jobs = 1 + HPC_MAX_CONTINUATIONS if lead else 1
        step_outputs = [o["name"] for o in
                        ((step.get("outputs") or {}).get("parameters") or [])]
        outputs_union.update(step_outputs)
        twin = {
            "name": task["name"] + "-" + provider,
            "template": "meluxina-run",
            "when": twin_when,
            "arguments": {"parameters": [
                {"name": "step-name", "value": task["name"]},
                {"name": "image", "value": container.get("image", "")},
                {"name": "step-command",
                 "value": _cmd_json(cmd, routed=routable, provider=provider)},
                {"name": "time-limit", "value": str(minutes)},
                {"name": "deadline-seconds",
                 "value": str(jobs * (minutes + QUEUE_ALLOWANCE_MINUTES) * 60)},
                {"name": "resumable-lead", "value": str(lead)},
                {"name": "step-outputs", "value": ",".join(step_outputs)},
                {"name": "hpc-class", "value": "{{workflow.parameters.%s-class}}" % step["name"]},
            ]},
        }
        if task.get("depends"):
            twin["depends"] = task["depends"]
        # Right after its in-cluster task, not at the end: the Argo UI's
        # template graph needs every dependency listed above its dependent,
        # and later steps depend on both twins (crashes reading 'genre').
        tasks.insert(tasks.index(task) + 1, twin)
        routed.append(task["name"])

    if not routed:
        return

    # F-05: downstream steps consume {{tasks.<routed>.outputs.parameters.P}}.
    # Exactly one twin ran; the other is Skipped and its outputs resolve to
    # their declared defaults ("{}"). Pick the twin that actually ran.
    def _pick(m):
        return "{{=%s}}" % _pair_expr(m.group(1), m.group(2), provider)
    ref_re = re.compile(r"\{\{\s*tasks\.(%s)\.outputs\.parameters\.([A-Za-z0-9_.-]+)\s*\}\}"
                        % "|".join(re.escape(r) for r in routed))
    for task in tasks:
        if task["name"].endswith("-" + provider):
            continue
        for p in ((task.get("arguments") or {}).get("parameters") or []):
            v = p.get("value")
            if isinstance(v, str) and ref_re.fullmatch(v.strip()):
                p["value"] = ref_re.sub(_pick, v.strip())

    # A bare task token in Argo depends grammar means Succeeded; a routed dep
    # is now a twin pair where exactly one twin runs and the other is Skipped.
    # Twins included: a twin whose upstream also ran on HPC must depend on
    # the upstream PAIR, not on the (Skipped) in-cluster task.
    # Status-qualified references (step.Succeeded || step.Skipped
    # || step.Omitted) must name the twin too: Argo exposes tasks.X to
    # a task's expressions ONLY for X in its depends, so a consumer whose
    # args pick tasks['X-meluxina'] hangs forever with "tasks.X-meluxina is
    # missing" (observed at run time, argo v4.0.6). Pair semantics:
    # Succeeded/Failed/Errored/Daemoned = either twin; Skipped/Omitted = both.
    def _status_pair(r):
        def sub(m):
            st = m.group(1)
            op = "&&" if st in ("Skipped", "Omitted") else "||"
            return "(%s.%s %s %s-%s.%s)" % (r, st, op, r, provider, st)
        return sub

    for task in tasks:
        dep = task.get("depends")
        if not dep:
            continue
        for r in routed:
            if task["name"] in (r, r + "-" + provider):
                continue
            dep = re.sub(r"(?<![\w.-])%s\.(Succeeded|Skipped|Omitted|Failed|Errored|Daemoned)(?![\w.-])"
                         % re.escape(r), _status_pair(r), dep)
            pair = ("((%s.Succeeded || %s.Skipped) && "
                    "(%s-%s.Succeeded || %s-%s.Skipped))"
                    % (r, r, r, provider, r, provider))
            dep = re.sub(r"(?<![\w.-])%s(?![\w.-])" % re.escape(r), pair, dep)
        task["depends"] = dep

    # F-08 wallet inputs: the machine key mounts optional:true (same shape
    # the legacy render-wft uses on every step) so a non-OIDC deployment
    # still submits — the submit code degrades to no-wallet loudly. The
    # dataset is the pipeline's `dataset` workflow parameter
    # (`<dataset-repo>@<version>`, parsed by the submit code); no param -> no
    # stage-in, batch runs the step data-less.
    mlflow_ctx = ctx.get("mlflow") or {}
    lakefs_ctx = ctx.get("lakefs") or {}
    wf_params = {p.get("name") for p in parameters}
    dataset = ("{{workflow.parameters.dataset}}"
               if "dataset" in wf_params else "")
    spec["templates"].append({
        "name": "meluxina-run",
        "inputs": {"parameters": [
            {"name": "step-name"}, {"name": "image"}, {"name": "step-command"},
            {"name": "time-limit"}, {"name": "deadline-seconds"},
            {"name": "step-outputs", "value": ""}, {"name": "hpc-class"},
            {"name": "resumable-lead", "value": "0"}]},
        # Per-step: Slurm time limit + queue/prep allowance (see
        # QUEUE_ALLOWANCE_MINUTES). Argo resolves the parameter here.
        "activeDeadlineSeconds": "{{inputs.parameters.deadline-seconds}}",
        # A lost waiter pod (node preemption, eviction, deletion) is not a
        # step failure: retry it — find_active() adopts the Slurm job by its
        # workflow-uid name, so a retried waiter re-attaches instead of
        # submitting a duplicate (a PENDING job on_term cancelled is
        # submitted afresh). A job that failed on MeluXina is not retried.
        "retryStrategy": {"limit": "2", "retryPolicy": "Always",
                          "expression": POD_LOSS_RETRY},
        "metadata": {"labels": {"platform.kubecore.io/compute-type": "hpc",
                                "platform.kubecore.io/hpc-class": "{{inputs.parameters.hpc-class}}"}},
        "volumes": [{"name": "mlflow-svc", "secret": {
            "secretName": str(mlflow_ctx.get("svcSecret") or "mlflow-svc"),
            "optional": True}},
                    # The rotated MeluXina JWT as a file: kubelet refreshes the
                    # mount on rotation, so long queue waits keep a valid token.
                    {"name": "meluxina-jwt", "secret": {"secretName": "meluxina-jwt",
                                                        "optional": True}},
                    # PRD-HPC-1541 F-03: forced-command staging key + login-node
                    # host pin. Optional: without it the job stages in-job.
                    # 0400: ssh refuses a group/world-readable key.
                    {"name": "meluxina-staging", "secret": {"secretName": "meluxina-staging",
                                                            "defaultMode": 0o400,
                                                            "optional": True}}],
        "container": {
            "image": "python:3.12-alpine",
            "command": ["python3", "-c", MELUXINA_SUBMIT_CODE],
            "volumeMounts": [{"name": "mlflow-svc",
                              "mountPath": "/etc/mlflow-svc",
                              "readOnly": True},
                             {"name": "meluxina-jwt",
                              "mountPath": "/etc/meluxina-jwt",
                              "readOnly": True},
                             {"name": "meluxina-staging",
                              "mountPath": "/etc/meluxina-staging",
                              "readOnly": True}],
            "env": [
                {"name": "SLURM_TOKEN", "valueFrom": {"secretKeyRef": {
                    "name": "meluxina-jwt", "key": "token"}}},
                {"name": "WF_UID", "value": "{{workflow.uid}}"},
                {"name": "STEP_NAME", "value": "{{inputs.parameters.step-name}}"},
                {"name": "IMAGE_REF", "value": "{{inputs.parameters.image}}"},
                {"name": "STEP_COMMAND", "value": "{{inputs.parameters.step-command}}"},
                {"name": "SLURM_TIME_LIMIT", "value": "{{inputs.parameters.time-limit}}"},
                {"name": "HPC_RESUMABLE_LEAD", "value": "{{inputs.parameters.resumable-lead}}"},
                {"name": "STEP_OUTPUTS", "value": "{{inputs.parameters.step-outputs}}"},
                {"name": "HPC_CLASS", "value": "{{inputs.parameters.hpc-class}}"},
                {"name": "HPC_CLASSES_JSON", "value": json.dumps(classes, separators=(",", ":"))},
                # PRD-HPC-1231: the PROJECT's HPC identity and filesystem layout,
                # published by the operator into pipeline-context hpc.* — the
                # runner carries no literal user/account/path (CON-05).
                {"name": "HPC_ACCOUNT", "value": str((ctx.get("hpc") or {}).get("account") or "")},
                {"name": "HPC_USER", "value": str((ctx.get("hpc") or {}).get("user") or "")},
                {"name": "HPC_SCRATCH", "value": str((ctx.get("hpc") or {}).get("scratch") or "")},
                {"name": "HPC_HOME", "value": str((ctx.get("hpc") or {}).get("home") or "")},
                {"name": "ZITADEL_MACHINE_KEY_FILE",
                 "value": "/etc/mlflow-svc/ZITADEL_MACHINE_KEY"},
                {"name": "ZITADEL_DOMAIN",
                 "value": str(mlflow_ctx.get("oidcDomain") or "")},
                {"name": "ZITADEL_MLFLOW_PROJECT_ID",
                 "value": str(mlflow_ctx.get("oidcProjectId") or "")},
                {"name": "MLFLOW_EXTERNAL_URL",
                 "value": str(mlflow_ctx.get("externalUrl") or "")},
                {"name": "LAKEFS_EXTERNAL_URL",
                 "value": str(lakefs_ctx.get("externalUrl") or "")},
                {"name": "DATASET", "value": dataset},
                # Pipeline outputs (stage-out hand-off, results) go to the
                # app's own outputs repository, on main.
                {"name": "OUTPUTS_REPO", "value": outputs_repo(ctx)},
                {"name": "OUTPUTS_REF", "value": OUTPUTS_REF},
                {"name": "CHECKPOINT_BUCKET", "value": outputs_repo(ctx)},
                {"name": "CHECKPOINT_PREFIX", "value": checkpoint_prefix()},
                {"name": "KUBECORE_RUN_ID", "value": "{{workflow.name}}"},
                {"name": "KUBECORE_WORKFLOW_NAME", "value": "{{workflow.name}}"},
            ] + ([{"name": KAOS_LIB_SUPPORT_ENV, "value": support_value(ctx)}] if support_value(ctx) else [])
              + sharing_env(ctx) + controller_env(ctx) + pull_env(ctx),
        },
        # slurm-job-id plus the union of every routed step's declared outputs
        # (one shared template; each twin fills its own, the rest default).
        "outputs": {"parameters": [{"name": "slurm-job-id",
                                    "valueFrom": {"path": "/tmp/slurm-job-id"}}]
                    + [{"name": n, "valueFrom": {"path": "/tmp/outputs/%s.json" % n,
                                                 "default": "{}"}}
                       for n in sorted(outputs_union)]},
    })
