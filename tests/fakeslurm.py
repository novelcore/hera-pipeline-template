#!/usr/bin/env python3
"""A fake Slurm for the slot manager tests: squeue, scontrol, srun and scancel over one
JSON state file (FAKE_SLURM_STATE), behaving like MeluXina's Slurm where the slot manager
depends on it (verified live 2026-11-03):

* `scontrol hold` works only on a pending job and shows it as PENDING/JobHeldUser;
* `squeue` without -t reports pending, running and completing jobs only;
* `srun` runs one job step with its own SLURM_STEP_ID and CUDA_VISIBLE_DEVICES;
* `scancel <job>.<step>` ends that step only.

Symlink it under each tool's name. Every call is appended to state["calls"].
"""
import fcntl
import json
import os
import signal
import subprocess
import sys

# A step's environment is clean (only Slurm's own variables), so the state file is also
# found next to the bin folder the tools are linked from.
STATE = os.environ.get("FAKE_SLURM_STATE") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0]))), "slurm.json")
TOOL = os.path.basename(sys.argv[0])
ARGS = sys.argv[1:]


def locked(fn):
    with open(STATE + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        with open(STATE) as f:
            st = json.load(f)
        st.setdefault("calls", []).append([TOOL] + ARGS)
        result = fn(st)
        with open(STATE, "w") as f:
            json.dump(st, f)
        return result


def fmt(text, values):
    for k, v in values.items():
        text = text.replace(k, str(v))
    return text


def job_values(jid, j):
    reason = "JobHeldUser" if j.get("held") else j.get("reason", "None")
    return {"%i": jid, "%j": j["name"], "%T": j["state"], "%r": reason, "%l": j.get("limit", "UNLIMITED"),
            "%P": j.get("partition", "gpu"), "%k": j.get("comment") or "(null)", "%e": j.get("end", "2099-01-01T00:00:00")}


def squeue(st):
    opts, i = {}, 0
    while i < len(ARGS):
        a = ARGS[i]
        if a in ("-j", "-o", "-u", "-t", "--sort"):
            opts[a] = ARGS[i + 1]
            i += 2
        else:
            opts[a] = True
            i += 1
    out = []
    if "-s" in opts:
        for sid, s in sorted(st.get("steps", {}).items()):
            if sid.split(".")[0] == opts["-j"]:
                out.append(fmt(opts["-o"], {"%i": sid, "%j": s["name"]}))
    else:
        states = ("PENDING",) if opts.get("-t") == "PENDING" else ("PENDING", "RUNNING", "COMPLETING")
        for jid in sorted(st["jobs"], key=int):
            j = st["jobs"][jid]
            if opts.get("-j") not in (None, jid) or j["state"] not in states:
                continue
            out.append(fmt(opts["-o"], job_values(jid, j)))
    print("\n".join(out))
    return 0


def scontrol(st):
    verb = ARGS[0]
    if verb in ("hold", "release"):
        j = st["jobs"].get(ARGS[1])
        if not j or j["state"] != "PENDING":
            print("scontrol: error: Job is no longer pending execution")
            return 1
        j["held"] = verb == "hold"
        return 0
    if verb == "update":
        kv = dict(a.split("=", 1) for a in ARGS[1:])
        st["jobs"][kv["JobId"]]["comment"] = kv.get("Comment", "")
        return 0
    if verb == "write" and ARGS[1] == "batch_script":
        with open(ARGS[3], "w") as f:
            f.write(st["jobs"][ARGS[2]]["script"])
        return 0
    return 1


def scancel(st):
    target = ARGS[0]
    if "." in target:
        s = st.get("steps", {}).get(target)
        if s:
            try:
                os.killpg(s["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        return 0
    if target in st["jobs"]:
        st["jobs"][target]["state"] = "CANCELLED"
    return 0


def srun():
    cmd, name, i = [], "step", 0
    while i < len(ARGS):
        a = ARGS[i]
        if a in ("-c", "--job-name"):
            if a == "--job-name":
                name = ARGS[i + 1]
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            cmd = ARGS[i:]
            break
    job = os.environ["SLURM_JOB_ID"]

    def register(st):
        n = st.setdefault("next_step", {}).get(job, 0)
        st["next_step"][job] = n + 1
        return n
    n = locked(register)
    env = dict(os.environ, SLURM_STEP_ID=str(n), CUDA_VISIBLE_DEVICES=str(n % 4))
    proc = subprocess.Popen(cmd, env=env, start_new_session=True)

    def started(st):
        st.setdefault("steps", {})["%s.%d" % (job, n)] = {"name": name, "pid": proc.pid}
    locked(started)
    rc = proc.wait()

    def ended(st):
        st["steps"].pop("%s.%d" % (job, n), None)
        st.setdefault("ended_steps", []).append({"name": name, "rc": rc})
    locked(ended)
    return 128 - rc if rc < 0 else rc


if __name__ == "__main__":
    if TOOL == "srun":
        sys.exit(srun())
    sys.exit(locked({"squeue": squeue, "scontrol": scontrol, "scancel": scancel}[TOOL]))
