"""PRD-HPC-1609 F-02: two MeluXina jobs (or two steps on one shared node) that need the
same image or the same dataset version write to the same Lustre cache at the same time.

* The image pull writes a name only this job uses, then renames it into the cache:
  a job never runs a half-written SIF, and an image another job already finished
  is kept.
* The dataset stage-in names its part-files per writer, so two writers of one file
  never interleave into one part-file.

The pull lines are taken from the real job script and run in bash against a fake
scratch and a fake apptainer.
Run:  python -m pytest tests/ -v
"""
import ast
import io
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kubecore.meluxina import MELUXINA_SUBMIT_CODE  # noqa: E402


def _job_script_lines():
    fn = next(n for n in ast.walk(ast.parse(MELUXINA_SUBMIT_CODE))
              if isinstance(n, ast.FunctionDef) and n.name == "submit")
    batch = next(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "batch")
    return [e.value for e in batch.value.args[0].elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def _pull_block():
    """From `if [ ! -f "$SIF" ]` to its `fi`: the job's image pull."""
    lines = _job_script_lines()
    start = lines.index('if [ ! -f "$SIF" ]; then')
    end = lines.index("fi", start)
    return lines[start:end + 1]


def _run_pull(tmp_path, apptainer_body):
    scr = tmp_path / "scratch"
    (scr / "sif-cache").mkdir(parents=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "apptainer").write_text("#!/bin/bash\n" + apptainer_body)
    (bindir / "apptainer").chmod(0o755)
    sif = scr / "sif-cache" / "abc.sif"
    script = "\n".join(['fail(){ echo "$1" > "$SCR/failed"; exit "$1"; }'] + _pull_block())
    env = dict(os.environ, SCR=str(scr), SIF=str(sif), IMAGE_REF="zot.example/p/app:v1",
               SLURM_JOB_ID="5417591", PATH=str(bindir) + os.pathsep + os.environ["PATH"])
    rc = subprocess.run(["bash", "-c", script], env=env).returncode
    return rc, scr, sif


def test_the_pull_never_writes_the_shared_name(tmp_path):
    # Fake pull: record the target, write it in two chunks.
    rc, scr, sif = _run_pull(tmp_path, 'echo "$2" > "$SCR/target"; printf half > "$2"; printf full >> "$2"\n')
    assert rc == 0
    target = (scr / "target").read_text().strip()
    assert target != str(sif), "a reader must never see a half-written SIF at the shared name"
    assert "5417591" in target, "the temporary name belongs to this job"
    assert sif.read_text() == "halffull"
    assert sorted(p.name for p in (scr / "sif-cache").iterdir()) == ["abc.sif"]


def test_an_image_another_job_finished_first_is_kept(tmp_path):
    # Another job finishes its rename while this one is still pulling.
    rc, scr, sif = _run_pull(tmp_path, 'printf winner > "$SIF"; printf mine > "$2"\n')
    assert rc == 0
    assert sif.read_text() == "winner"
    assert sorted(p.name for p in (scr / "sif-cache").iterdir()) == ["abc.sif"], "no part-file left"


def test_a_failed_pull_leaves_nothing_and_fails_231(tmp_path):
    rc, scr, sif = _run_pull(tmp_path, 'printf partial > "$2"; exit 1\n')
    assert rc == 231 and (scr / "failed").read_text().strip() == "231"
    assert list((scr / "sif-cache").iterdir()) == [], "no half image, no part-file"


def test_stale_part_files_are_cleaned_after_half_a_day():
    lines = _job_script_lines()
    assert any(l.startswith('find $SCR/sif-cache') and '*.sif.part-*' in l and '-mmin +720' in l
               for l in lines), "a pull killed mid-way must not leak its part-file forever"


# ---------------------------------------------------------------- dataset stage-in

class _LakeFS:
    def __init__(self, objects):
        self.objects = objects

    def __call__(self, req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        if "/objects/ls?" in url:
            res = [{"path": p, "path_type": "object", "size_bytes": len(b)} for p, b in self.objects.items()]
            return io.BytesIO(json.dumps({"results": res, "pagination": {"has_more": False}}).encode())
        if "/objects?" in url:
            return io.BytesIO(self.objects[urllib.request.unquote(url.split("path=", 1)[1])])
        return io.BytesIO(b"{}")


def test_stage_in_part_files_are_per_writer(tmp_path, monkeypatch):
    for k, v in {"LAKEFS_ENDPOINT": "https://lakefs.example", "LAKEFS_BEARER_TOKEN": "jwt",
                 "DATASET_REPO": "dataset-cars", "DATASET_REF": "v1", "DATASET_COMMIT": "c0ffee",
                 "DATASET_CACHE": str(tmp_path / "cache"), "DATASET_DIRFILE": str(tmp_path / "dir"),
                 "SLURM_JOB_ID": "5417595"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(urllib.request, "urlopen", _LakeFS({"data.yaml": b"mine"}))
    dest = tmp_path / "cache" / "dataset-cars" / "c0ffee"
    dest.mkdir(parents=True)
    # Another writer (a job on another node) is half-way through the same file.
    (dest / "data.yaml.part").write_bytes(b"other writer's bytes")
    g = {}
    exec(MELUXINA_SUBMIT_CODE.split("API = ")[0], g)
    exec(g["STAGEIN"], {})
    assert (dest / "data.yaml").read_bytes() == b"mine"
    assert (dest / "data.yaml.part").read_bytes() == b"other writer's bytes", \
        "this writer must not write into another writer's part-file"
    assert not [p for p in dest.iterdir() if ".part-" in p.name], "own part-files are renamed away"
