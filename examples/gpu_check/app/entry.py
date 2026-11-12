"""gpu-check: the example GPU step. Proves the step can use its GPU, then does a few seconds of real GPU work.

It fails at once, with a clear message, when torch cannot see a GPU: a GPU step that silently trains on the
CPU for hours is the failure this step exists to rule out. Replace the body with your own training code and
keep the `require_gpu()` call at the top of it.
"""

import sys

from kaos_lib import step

WORK_SECONDS = 15  # long enough to show up as GPU use to the platform's idle watchdog
MATRIX_SIZE = 4096


def require_gpu(torch) -> str:
    """Return the GPU's name, or exit non-zero when torch cannot use a GPU."""
    if not torch.cuda.is_available():
        sys.exit("[gpu-check] torch cannot see a GPU (torch.cuda.is_available() is False). The step image or the "
                 "machine is not set up for GPU: this step would train on the CPU. See "
                 "https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/bigger-machines.html.")
    return torch.cuda.get_device_name(0)


def burn_gpu(torch, seconds: float) -> float:
    """Multiply two large matrices on the GPU for `seconds`; return the achieved TFLOPS."""
    import time
    a = torch.randn(MATRIX_SIZE, MATRIX_SIZE, device="cuda", dtype=torch.float16)
    b = torch.randn(MATRIX_SIZE, MATRIX_SIZE, device="cuda", dtype=torch.float16)
    torch.cuda.synchronize()
    start, done = time.monotonic(), 0
    while time.monotonic() - start < seconds:
        a @ b
        done += 1
        torch.cuda.synchronize()
    return done * 2 * MATRIX_SIZE ** 3 / (time.monotonic() - start) / 1e12


def main() -> None:
    ctx = step.start()
    import torch  # imported here so the tests can run the helpers with a stand-in

    print(f"[gpu-check] experiment {ctx.experiment}: torch {torch.__version__}, "
          f"CUDA runtime {torch.version.cuda}", flush=True)
    name = require_gpu(torch)
    print(f"[gpu-check] GPU visible: {name} ({torch.cuda.device_count()} device(s))", flush=True)
    tflops = burn_gpu(torch, WORK_SECONDS)
    print(f"[gpu-check] ran on {name}: {tflops:.1f} TFLOPS (fp16 matmul). The GPU works.", flush=True)
    step.result(gpu=name, tflops=round(tflops, 1))


if __name__ == "__main__":
    main()
