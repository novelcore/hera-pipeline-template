"""compose-and-validate keeps every form value in the type its config leaf
declares (Hydra numeric/bool/null coercion bug: `probe.label=3e286280` reached
Hydra bare, parsed as 3x10^286280 = inf, and params.yaml said `label: .inf`).

Run:  python -m pytest tests/ -v
"""

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import pytest
import yaml
from hydra.core.config_store import ConfigStore

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kubecore import compose, derive_tree  # noqa: E402

LEAVES = {
    "label": "baseline",   # str
    "name": "run",         # str
    "epochs": 3,           # int
    "lr": 0.01,            # float
    "flag": False,         # bool
    "note": None,          # untyped null -> string
    "sizes": [1, 2],       # list
}

STRING_LOOKALIKES = ["3e286280", "1234", "1e5", "true", "null", "nan", "inf", "0x1f",
                     "-7", "False", "~", "1_000"]


class Mode(Enum):
    none = "none"
    ptq = "ptq"


@dataclass
class TypedSection:
    tag: str = "v1"
    steps: int = 5
    ratio: float = 0.5
    on: bool = True
    seed: Optional[int] = None
    mode: Mode = Mode.none


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A throwaway config tree: an untyped yaml section `probe`, a group
    `model` (whose options change a leaf's type), and a schema-typed section."""
    cfg = tmp_path / "config"
    (cfg / "model").mkdir(parents=True)
    ConfigStore.instance().store(name="typed_schema_test", node={"typed": TypedSection})
    (cfg / "config.yaml").write_text(yaml.safe_dump({
        "defaults": ["typed_schema_test", "_self_", {"model": "small"}],
        "probe": LEAVES,
        "typed": {"tag": "v1"},
    }, sort_keys=False))
    (cfg / "model" / "small.yaml").write_text("size: 8\n")
    (cfg / "model" / "named.yaml").write_text("size: tiny\n")
    monkeypatch.setattr(derive_tree, "CONFIG_DIR", cfg)
    monkeypatch.setattr(derive_tree, "PLATFORM_SEARCHPATH", tmp_path)
    return cfg


def resolved(tokens, render_defaults=None):
    """Full compose path; returns the params.yaml text parsed back (the
    downstream steps' view)."""
    text = compose.compose_and_validate(tokens, render_defaults=render_defaults or {})
    return text, yaml.safe_load(text)


# ------------------------------------------------------- string leaves


@pytest.mark.parametrize("value", STRING_LOOKALIKES)
def test_string_param_stays_string(tree, value):
    text, out = resolved([f"probe.label={value}"])
    assert out["probe"]["label"] == value
    assert isinstance(out["probe"]["label"], str)


def test_reported_case_3e286280_is_not_inf(tree):
    text, out = resolved(["probe.label=3e286280"])
    assert ".inf" not in text
    assert out["probe"]["label"] == "3e286280"


@pytest.mark.parametrize("value", [
    "my run", 'say "hi"', "it's", "a=b", "k=v=w", "📊 Data summary",
    "C:\\data\\x", "trail\\", 'back\\"quote', "a,b", "[1,2]", "{a: 1}", "$x", "  ",
])
def test_string_special_characters_round_trip(tree, value):
    _, out = resolved([f"probe.name={value}"])
    assert out["probe"]["name"] == value.strip()  # surrounding whitespace is stripped (#867)


def test_untyped_null_leaf_takes_string(tree):
    _, out = resolved(["probe.note=1234"])
    assert out["probe"]["note"] == "1234"


def test_typed_str_leaf_stays_string(tree):
    _, out = resolved(["typed.tag=1e5"])
    assert out["typed"]["tag"] == "1e5"


def test_enum_leaf_accepts_its_value(tree):
    _, out = resolved(["typed.mode=ptq"])
    assert out["typed"]["mode"] == "ptq"


# ------------------------------------------------- numeric / bool leaves


def test_int_param_stays_int(tree):
    _, out = resolved(["probe.epochs=10"])
    assert out["probe"]["epochs"] == 10 and type(out["probe"]["epochs"]) is int


def test_float_param_stays_float(tree):
    _, out = resolved(["probe.lr=0.5"])
    assert out["probe"]["lr"] == 0.5 and type(out["probe"]["lr"]) is float


def test_float_param_given_integer_text_stays_float(tree):
    _, out = resolved(["probe.lr=1"])
    assert out["probe"]["lr"] == 1.0 and type(out["probe"]["lr"]) is float


def test_float_param_scientific(tree):
    _, out = resolved(["probe.lr=1e-4"])
    assert out["probe"]["lr"] == pytest.approx(1e-4)


def test_bool_param_stays_bool(tree):
    _, out = resolved(["probe.flag=True"])
    assert out["probe"]["flag"] is True


def test_typed_schema_numbers_and_optional_int(tree):
    _, out = resolved(["typed.steps=7", "typed.ratio=2", "typed.on=false", "typed.seed=42"])
    assert out["typed"] == {"tag": "v1", "steps": 7, "ratio": 2.0, "on": False, "seed": 42,
                            "mode": "none"}
    assert type(out["typed"]["ratio"]) is float


@pytest.mark.parametrize("token", ["probe.epochs=ten", "probe.epochs=1.5", "probe.lr=fast",
                                   "probe.flag=yes", "typed.steps=0x1f"])
def test_invalid_literal_for_typed_leaf_fails_compose(tree, token):
    with pytest.raises(compose.ComposeError):
        resolved([token])


# --------------------------------------------- groups, lists, quoting, elision


def test_type_follows_the_selected_group(tree):
    # model/small.yaml declares size as int; model/named.yaml as str
    _, out = resolved(["model=named", "model.size=123"])
    assert out["model"]["size"] == "123"
    _, out = resolved(["model=small", "model.size=123"])
    assert out["model"]["size"] == 123


def test_list_leaf_passes_through(tree):
    _, out = resolved(["probe.sizes=[3,4]"])
    assert out["probe"]["sizes"] == [3, 4]


def test_already_quoted_values_are_kept(tree):
    assert compose.order_overrides(['probe.label="3e286280"'], {}) == ['probe.label="3e286280"']
    assert compose.order_overrides(["probe.epochs='10'"], {}) == ["probe.epochs='10'"]
    _, out = resolved(["probe.label='3e286280'"])
    assert out["probe"]["label"] == "3e286280"


def test_untouched_leaf_elided_and_groups_first(tree):
    tokens = compose.order_overrides(
        ["probe.label=baseline", "probe.epochs=10\r", "model=named"],
        {"probe.label": "baseline", "probe.epochs": "3", "model": "small"},
    )
    assert tokens == ["model=named", "probe.epochs=10"]


def test_emitted_tokens(tree):
    tokens = compose.order_overrides(
        ["probe.label=3e286280", "probe.epochs=10", "probe.lr=1", "probe.flag=TRUE",
         'probe.name=a "b" \\c\\'], {})
    assert tokens == ['probe.label="3e286280"', "probe.epochs=10", "probe.lr=1.0",
                      "probe.flag=true", 'probe.name="a \\"b\\" \\c\\\\"']


def test_unknown_key_still_rejected(tree):
    with pytest.raises(Exception):
        resolved(["probe.labl=x"])
