# GPU steps

**Goal:** add a step that trains or runs on a GPU, and know the platform checks, in the first second, that the step
can really use it.

A step is a GPU step when you declare it in `pipeline.py` with `gpu=True`. On your project's own GPU machines the
platform then does two things for you before your code starts:

1. It puts the machine's NVIDIA driver folders in front of the library and program search paths of your image
   (`/usr/local/nvidia/lib64`, `/usr/local/nvidia/lib` and `/usr/local/nvidia/bin`). Whatever your image already
   sets stays; the platform only adds to it. Your command, its arguments and its exit code are not changed.
2. It checks that the NVIDIA driver can be started. When it cannot, the step **fails in its first second** with
   this line in its log:

```text
KAOS: this GPU step cannot reach the NVIDIA driver (libcuda.so.1 not found: ...); the image or node is not set up for GPU
```

Without that check, a step whose image cannot find the driver does not fail: torch quietly falls back to the CPU and
the run trains for hours at a fraction of the speed.

## Add the example GPU step

The template ships one in `examples/gpu_check/`: a small torch program that prints the GPU it uses and runs a few
seconds of work on it, plus a known-good Dockerfile. It is not part of your pipeline until you copy it in.

1. Copy the folder into your steps. The folder name uses underscores (see [Add a step](add-a-step.md)).

    ```bash
    cp -r examples/gpu_check steps/gpu_check
    ```

2. Add one line to `pipeline.py`, inside the `with pipeline(...)` block:

    ```python
    gpu_check = step("gpu-check", reads=["experiment"], needs=[load], gpu=True)
    ```

3. Send your change in, as in [Send your change in and go live](send-it-in.md), and run the pipeline.
4. On the submit form, `gpu-check-class` lists your project's classes. Pick a GPU class (the default for a GPU step
   is already one).

In the step's log you should see lines like:

```text
[gpu-check] GPU visible: NVIDIA L4 (1 device(s))
[gpu-check] ran on NVIDIA L4: 20.3 TFLOPS (fp16 matmul). The GPU works.
```

If you pick a class without a GPU for a GPU step, the step runs on the CPU on purpose and the driver check is skipped.
The example then stops with its own message, because torch sees no GPU.

## A GPU image that works

`examples/gpu_check/Dockerfile` is a plain Python image with a pinned pip `torch`. The pip wheel carries its own CUDA
runtime libraries; only the NVIDIA driver comes from the machine. Three rules keep your own image working:

- **Use a CUDA-enabled torch.** The default `pip install torch` wheel on Linux is. A CPU-only build (for example
  from the `cpu` wheel index) never uses the GPU, whatever the machine offers.
- **Keep the two `ENV` lines** that set `LD_LIBRARY_PATH` and `PATH` to the NVIDIA folders. The platform adds the same
  folders on its GPU machines, so they change nothing there. They make the image work on other machines too: your
  own GPU workstation with the NVIDIA container runtime, or another cluster.
- **Keep a shell in the image.** The GPU wrapper starts your command through `/bin/sh`, so an image with no shell
  (a distroless image) cannot be a GPU step. If the image has no `python3`, the driver check is skipped with the
  line `KAOS: python3 not found in the image; skipping the NVIDIA driver check` and the step still runs.

Images based on `nvidia/cuda` or on conda (`continuumio/miniconda3`) work the same way. Their own library path is kept.

## If the step fails with the driver message

| the message says | what it means | what to do |
|---|---|---|
| `libcuda.so.1 not found` | the image cannot find the machine's NVIDIA driver | pick a class that has a GPU; if you did, tell your platform contact: the machine is not set up for GPU |
| `cuInit returned error 100` | the machine shows no GPU to the step | the same: pick a GPU class, or tell your platform contact |
| `torch cannot see a GPU` (your own code or the example) | the image's torch has no CUDA support | install a CUDA-enabled torch, see above |

Your pipeline's `kaosctl lint` also warns (rule `L-D08`) about a GPU step whose Dockerfile starts from a plain
non-CUDA base and does not set the driver paths. The warning is about running that image outside the platform's GPU
machines; it does not stop you from sending a change in.

## On HPC (Slurm)

A step you place on an HPC (Slurm) class runs through the HPC provider's own GPU support. The platform does not add
the wrapper or the driver check there: they are only for your project's own GPU machines. The same image and the same
command work in both places.
