"""PRD-HPC-1461 / PRD-1609: what the in-pod runner reports for settlement. Live 2026-11-06 on the dev lab
(host 5427313 on mel2034 ran guests 5427315 and 5427316 as steps) the guests reported a start of
2106-02-07 (Slurm's unset time) and no host, and the host reported no end: the controller settled
-41,683,737 node-minutes per guest and 0 for the host. Unset times are absent, a terminal job always
has an end, and every report names the host a guest ran on.

Run:  python -m pytest tests/ -v
"""
import ast
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kubecore.meluxina import MELUXINA_SUBMIT_CODE as SRC  # noqa: E402

G = {"time": time}
_tree = ast.parse(SRC)
exec("\n\n".join(ast.get_source_segment(SRC, n) for n in _tree.body
                 if isinstance(n, ast.FunctionDef) and n.name in ("site_time", "ended", "shared")), G)
site_time, ended, shared = G["site_time"], G["ended"], G["shared"]


def test_unset_slurm_times_are_absent():
    for t in ({"set": False, "infinite": False, "number": 0}, {"set": True, "infinite": True, "number": 0},
              {"set": True, "infinite": False, "number": 4294967294}, 4294967294, 4294967295, 0, None):
        assert site_time({"time": {"start": t}}, "start") is None, t


def test_a_set_time_is_a_date():
    assert site_time({"time": {"start": {"set": True, "infinite": False, "number": 1762406933}}}, "start") \
        == "2025-11-06T05:28:53Z"
    assert site_time({"time": {"end": 1762406933}}, "end") == "2025-11-06T05:28:53Z"


def test_a_terminal_job_always_has_an_end():
    assert ended({"time": {"end": 1762406933}}) == "2025-11-06T05:28:53Z"
    got = ended({"time": {"end": {"set": False}}})   # the host whose end accounting had not landed
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", got)
    assert abs(time.mktime(time.strptime(got, "%Y-%m-%dT%H:%M:%SZ")) - time.mktime(time.gmtime())) < 5


def test_every_report_names_the_host_of_a_guest():
    assert shared({"kaos-state": "done", "rc": "0", "host": "5427313"}) == {"hostSiteJobID": "5427313", "slot": None}
    assert shared({"kaos-state": "taken", "host": "5427313", "slot": "2"}) == {"hostSiteJobID": "5427313", "slot": 2}
    assert shared({}) == {"hostSiteJobID": None, "slot": None}


def test_terminal_reports_carry_the_end_and_the_host():
    reports = [SRC[m.start():m.start() + 400].split("terminal=True")[0] + SRC[m.start():].split("terminal=True", 1)[1][:40]
               for m in re.finditer(r"report\(must=True", SRC)]
    assert len(reports) == 3
    for r in reports:
        assert "endTime=ended(job)" in r and "**shared(share)" in r, r
