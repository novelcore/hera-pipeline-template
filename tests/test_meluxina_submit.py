"""A job MeluXina's slurmrestd refuses names the reason in the step log: the
server answers HTTP 500 with errors/warnings in the body (2026-11-01: both e2e
submits died on a bare 'HTTP Error 500: INTERNAL ERROR').
Run:  python -m pytest tests/ -v
"""

import ast
import io
import json
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kubecore.meluxina import MELUXINA_SUBMIT_CODE  # noqa: E402


def _refusal():
    fn = next(n for n in ast.parse(MELUXINA_SUBMIT_CODE).body
              if isinstance(n, ast.FunctionDef) and n.name == "submit_refusal")
    g = {"json": json}
    exec(ast.get_source_segment(MELUXINA_SUBMIT_CODE, fn), g)
    return g["submit_refusal"]


def _error(code, body: bytes):
    return urllib.error.HTTPError("https://slurm-api.lxp.lu/slurm/v0.0.44/job/submit", code,
                                  "INTERNAL ERROR", {}, io.BytesIO(body))


def test_the_refusal_names_slurms_reasons():
    body = {"errors": [{"description": "Invalid qos specification", "error_number": 2066}],
            "warnings": [], "job_id": None}
    out = _refusal()(_error(500, json.dumps(body).encode()))
    assert out.startswith("HTTP 500 ")
    assert "Invalid qos specification" in out and "2066" in out
    assert "warnings" not in out   # empty fields are left out


def test_a_body_without_json_still_names_the_status():
    assert _refusal()(_error(502, b"<html>bad gateway</html>")) == \
        "HTTP 502 (no reason in the body)"


def test_submit_reports_the_refusal_before_exiting():
    fn = next(n for n in ast.parse(MELUXINA_SUBMIT_CODE).body
              if isinstance(n, ast.FunctionDef) and n.name == "submit")
    src = ast.get_source_segment(MELUXINA_SUBMIT_CODE, fn)
    assert "except urllib.error.HTTPError as e:" in src
    assert "submit_refusal(e)" in src
