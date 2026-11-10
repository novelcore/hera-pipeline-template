"""GPU driver prelude: a gpu step on a KAOS GPU node gets its command wrapped so the NVIDIA driver is reachable.

The enhancer wraps only gpu steps, only the in-cluster container (never the HPC/Slurm twin), and the wrapper
runs the original command unchanged. The shell tests run the real prelude under `sh`.
Run:  python -m pytest tests/ -v
"""
import copy
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kubecore import authoring, enhance, meluxina  # noqa: E402

BASE = yaml.safe_load((ROOT / "kubecore" / "local-dev" / "pipeline-context.yaml").read_text())
ORIGINAL_COMMAND = ["python", "-m", "app.entry"]
PRELUDE_HEAD = ["sh", "-c", enhance.GPU_PRELUDE_SCRIPT, enhance.GPU_PRELUDE_NAME]


def _render(ctx):
    with authoring.pipeline("t") as p:
        authoring.step("prep")
        authoring.step("train", gpu=True)
        authoring.step("pinned", gpu=True, hpc_time_limit="30m")
    wf = enhance.enhance(yaml.safe_load(p.wt.to_yaml()), ctx)
    return {t["name"]: t for t in wf["spec"]["templates"]}


@pytest.fixture(scope="module")
def tpls():
    ctx = copy.deepcopy(BASE)
    ctx.pop("hpc")
    return _render(ctx)


def test_should_wrap_the_gpu_step_command_and_keep_the_original_after_it(tpls):
    c = tpls["train"]["container"]
    assert c["command"][:4] == PRELUDE_HEAD
    assert c["command"][5:] == ORIGINAL_COMMAND
    assert c["args"][:2] == ["--params", "{{inputs.parameters.params}}"]


def test_should_pass_the_runtime_gpu_count_so_a_cpu_class_skips_the_check(tpls):
    assert tpls["train"]["container"]["command"][4] == "{{inputs.parameters.gpus}}"


def test_should_not_wrap_a_cpu_step(tpls):
    assert tpls["prep"]["container"]["command"] == ORIGINAL_COMMAND


def test_should_not_wrap_the_compose_step(tpls):
    assert tpls["compose-and-validate"]["container"]["command"][0] == "python"


def test_should_wrap_once_when_enhancing_twice(tpls):
    step = copy.deepcopy(tpls["train"])
    before = step["container"]["command"]
    enhance.enhance_gpu_driver(step)
    assert step["container"]["command"] == before


def test_should_leave_a_step_without_an_explicit_command_alone():
    step = {"name": "x", "container": {"image": "i"}}
    enhance.enhance_gpu_driver(step)
    assert "command" not in step["container"]


def test_should_keep_the_prelude_out_of_the_hpc_twin_and_the_follower():
    tpls = _render(copy.deepcopy(BASE))
    assert tpls["train"]["container"]["command"][:4] == PRELUDE_HEAD  # the KAOS (in-cluster) leg is wrapped
    dag = next(t for t in tpls.values() if "dag" in t)["dag"]["tasks"]
    twin = next(t for t in dag if t["name"] == "train-" + BASE["hpc"]["provider"])
    cmd = next(p["value"] for p in twin["arguments"]["parameters"] if p["name"] == "step-command")
    assert enhance.GPU_PRELUDE_NAME not in cmd and "nvidia" not in cmd and "app.entry" in cmd
    assert enhance.GPU_PRELUDE_NAME not in str(tpls[meluxina.HPC_TWIN_TEMPLATE])


def test_should_contain_no_argo_or_kubernetes_expansion_syntax():
    script = enhance.GPU_PRELUDE_SCRIPT
    assert "{{" not in script and "$(" not in script


# ---- the prelude run for real under sh --------------------------------------------------------------------

def _run(args, env=None, gpus="1"):
    full = {"PATH": os.environ["PATH"], **(env or {})}
    return subprocess.run(["sh", "-c", enhance.GPU_PRELUDE_SCRIPT, enhance.GPU_PRELUDE_NAME, gpus] + args,
                          capture_output=True, text=True, env=full)


def test_should_fail_in_the_first_second_with_the_message_when_libcuda_is_absent():
    res = _run(["echo", "ran"])
    assert res.returncode == 1 and "ran" not in res.stdout
    assert res.stderr.startswith("KAOS: this GPU step cannot reach the NVIDIA driver (libcuda.so.1 not found")
    assert res.stderr.rstrip().endswith("the image or node is not set up for GPU")


def test_should_skip_the_check_when_the_step_got_no_gpu():
    res = _run(["echo", "ran"], gpus="0")
    assert (res.returncode, res.stdout.strip()) == (0, "ran")


def test_should_prepend_the_driver_paths_and_keep_the_images_own_values():
    res = _run(["sh", "-c", 'echo "$LD_LIBRARY_PATH|$PATH"'],
               env={"LD_LIBRARY_PATH": "/opt/conda/lib:/opt/x"}, gpus="0")
    ld, path = res.stdout.strip().split("|")
    assert ld == "/usr/local/nvidia/lib64:/usr/local/nvidia/lib:/opt/conda/lib:/opt/x"
    assert path.startswith("/usr/local/nvidia/bin:") and os.environ["PATH"] in path


def test_should_not_leave_a_trailing_colon_when_the_image_sets_no_library_path():
    res = _run(["sh", "-c", 'echo "$LD_LIBRARY_PATH"'], gpus="0")
    assert res.stdout.strip() == "/usr/local/nvidia/lib64:/usr/local/nvidia/lib"


def test_should_preserve_the_exit_code_and_arguments_of_the_original_command():
    res = _run(["sh", "-c", 'echo "$1|$2"; exit 7', "x", "a b", "c"], gpus="0")
    assert res.returncode == 7 and res.stdout.strip() == "a b|c"


def test_should_skip_with_a_notice_when_the_image_has_no_python3(tmp_path):
    for tool in ("sh", "echo"):
        (tmp_path / tool).symlink_to(shutil.which(tool))
    res = _run(["echo", "ran"], env={"PATH": str(tmp_path)})
    assert (res.returncode, res.stdout.strip()) == (0, "ran")
    assert "python3 not found in the image; skipping the NVIDIA driver check" in res.stderr


@pytest.mark.skipif(not shutil.which("gcc"), reason="needs gcc to build a stub libcuda")
@pytest.mark.parametrize("rc,ok", [(0, True), (100, False)], ids=["cuInit_ok", "cuInit_no_device"])
def test_should_run_the_command_only_when_cuinit_succeeds(tmp_path, rc, ok):
    src = tmp_path / "s.c"
    src.write_text("int cuInit(unsigned f){(void)f; return %d;}" % rc)
    subprocess.run(["gcc", "-shared", "-fPIC", "-o", str(tmp_path / "libcuda.so.1"), str(src)], check=True)
    res = _run(["echo", "ran"], env={"LD_LIBRARY_PATH": str(tmp_path)})
    if ok:
        assert (res.returncode, res.stdout.strip()) == (0, "ran")
    else:
        assert res.returncode == 1 and "cuInit returned error 100" in res.stderr
