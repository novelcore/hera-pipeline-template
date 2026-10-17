"""PRD #1034 (app connections): the enhancer appends optional envFrom refs to
the connection ConfigMaps listed in pipeline-context `connections[]` on every
developer step, and never on platform templates (meluxina-run).
Run:  python -m pytest tests/ -v
"""

import copy
import runpy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kubecore import enhance  # noqa: E402

CONTEXT = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())
CATALOG = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "dataset-catalog.yaml").read_text())

CONNS = [
    {"name": "inference", "envPrefix": "INFERENCE", "configMapName": "cm-inference", "environment": "runtime"},
    {"name": "features", "envPrefix": "FEATURES", "configMapName": "cm-features"},
    {"name": "other-env", "envPrefix": "OTHER_ENV", "configMapName": "cm-other", "environment": "train"},
]
WANT = [
    {"configMapRef": {"name": "cm-inference", "optional": True}},
    {"configMapRef": {"name": "cm-features", "optional": True}},
]


def _ctx(conns, env="runtime"):
    """Deep copy of the local-dev context. conns None removes the key; env None
    removes mlEnvironment."""
    ctx = copy.deepcopy(CONTEXT)
    if conns is None:
        ctx.pop("connections", None)
    else:
        ctx["connections"] = copy.deepcopy(conns)
    if env is None:
        ctx.pop("mlEnvironment", None)
    else:
        ctx["mlEnvironment"] = {**(ctx.get("mlEnvironment") or {}), "name": env}
    return ctx


def _raw():
    ns = runpy.run_path(str(ROOT / "pipeline.py"), run_name="__pipeline__")
    return yaml.safe_load(ns["p"].wt.to_yaml())


def _raw_container_names():
    return [t["name"] for t in _raw()["spec"]["templates"] if "container" in t]


def _enhanced(ctx, raw=None):
    return enhance.enhance(copy.deepcopy(raw) if raw is not None else _raw(), ctx, CATALOG)


def _users(out):
    names = set(_raw_container_names())
    return [t for t in out["spec"]["templates"] if t["name"] in names]


def test_envfrom_optional_true():
    users = _users(_enhanced(_ctx(CONNS)))
    assert users and all(t["container"]["envFrom"] == WANT for t in users)


def test_envfrom_is_last_container_key():
    for t in _users(_enhanced(_ctx(CONNS))):
        assert list(t["container"])[-1] == "envFrom"


def test_platform_templates_untouched():
    t = {t["name"]: t for t in _enhanced(_ctx(CONNS))["spec"]["templates"]}
    assert "meluxina-run" in t and "envFrom" not in t["meluxina-run"]["container"]


def test_meluxina_twin_untouched():
    a, b = _enhanced(_ctx(CONNS)), _enhanced(_ctx(None))
    mr = lambda w: next(t for t in w["spec"]["templates"] if t["name"] == "meluxina-run")
    assert mr(a) == mr(b)
    dag = lambda w: next(t for t in w["spec"]["templates"] if "dag" in t)
    assert dag(a) == dag(b)  # twin tasks unchanged


def test_env_filtering():
    got = [t["container"]["envFrom"] for t in _users(_enhanced(_ctx(CONNS, env="runtime")))]
    assert got and all(g == WANT for g in got)
    # no mlEnvironment: entries carrying an environment are dropped
    got = [t["container"]["envFrom"] for t in _users(_enhanced(_ctx(CONNS, env=None)))]
    assert got and all(g == [WANT[1]] for g in got)
    # an environment that matches only the "train" entry
    got = [t["container"]["envFrom"] for t in _users(_enhanced(_ctx(CONNS, env="train")))]
    assert got and all(g == [WANT[1], {"configMapRef": {"name": "cm-other", "optional": True}}] for g in got)


def test_empty_environment_means_absent():
    conns = [{"name": "a", "envPrefix": "A", "configMapName": "cm-a", "environment": ""}]
    for env in ("runtime", None):
        users = _users(_enhanced(_ctx(conns, env=env)))
        assert users and all(
            t["container"]["envFrom"] == [{"configMapRef": {"name": "cm-a", "optional": True}}] for t in users
        )


def test_entry_without_configmap_name_skipped():
    conns = [{"name": "x", "envPrefix": "X"}, {"name": "y", "envPrefix": "Y", "configMapName": ""}]
    out = _enhanced(_ctx(conns))
    assert all("envFrom" not in t.get("container", {}) for t in out["spec"]["templates"])


def test_duplicate_configmap_names_collapsed():
    conns = [
        {"name": "a", "envPrefix": "A", "configMapName": "cm-dup"},
        {"name": "b", "envPrefix": "B", "configMapName": "cm-dup"},
    ]
    for t in _users(_enhanced(_ctx(conns))):
        assert t["container"]["envFrom"] == [{"configMapRef": {"name": "cm-dup", "optional": True}}]


def test_developer_envfrom_kept():
    raw = _raw()
    mine = [{"configMapRef": {"name": "mine"}}, {"configMapRef": {"name": "cm-features"}}]
    for t in raw["spec"]["templates"]:
        if "container" in t:
            t["container"]["envFrom"] = copy.deepcopy(mine)
    out = _enhanced(_ctx(CONNS), raw)
    want = [
        {"configMapRef": {"name": "mine"}},
        {"configMapRef": {"name": "cm-features"}},
        {"configMapRef": {"name": "cm-inference", "optional": True}},
    ]
    users = _users(out)
    assert users and all(t["container"]["envFrom"] == want for t in users)


def test_no_connections_identical():
    raw = _raw()
    dump = lambda w: yaml.safe_dump(w, sort_keys=False, default_flow_style=False)
    a = dump(enhance.enhance(copy.deepcopy(raw), _ctx(None), CATALOG))
    b = dump(enhance.enhance(copy.deepcopy(raw), _ctx([]), CATALOG))
    assert a == b and "envFrom" not in a


def test_envfrom_no_yaml_aliases():
    out = yaml.safe_dump(_enhanced(_ctx(CONNS)), sort_keys=False, default_flow_style=False)
    assert "&id" not in out and "*id" not in out


def test_null_or_non_list_envfrom_treated_as_absent():
    for bad in (None, "oops", {"configMapRef": {"name": "x"}}):
        raw = _raw()
        for t in raw["spec"]["templates"]:
            if "container" in t:
                t["container"]["envFrom"] = copy.deepcopy(bad)
        users = _users(_enhanced(_ctx(CONNS), raw))
        assert users and all(t["container"]["envFrom"] == WANT for t in users), bad
