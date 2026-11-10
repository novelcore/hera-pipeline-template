"""The example GPU step: it fails loudly without a GPU and reports the GPU it used."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ENTRY = Path(__file__).resolve().parents[1] / "examples" / "gpu_check" / "app" / "entry.py"
spec = importlib.util.spec_from_file_location("gpu_check_entry", ENTRY)
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


def _torch(available, name="NVIDIA L4"):
    cuda = SimpleNamespace(is_available=lambda: available, get_device_name=lambda i: name)
    return SimpleNamespace(cuda=cuda)


def test_should_return_the_gpu_name_when_torch_sees_a_gpu():
    assert entry.require_gpu(_torch(True)) == "NVIDIA L4"


def test_should_exit_with_a_clear_message_when_torch_sees_no_gpu():
    with pytest.raises(SystemExit) as err:
        entry.require_gpu(_torch(False))
    assert "would train on the CPU" in str(err.value)
