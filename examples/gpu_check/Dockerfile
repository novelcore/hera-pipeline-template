# Known-good GPU step image: a plain python base plus a pip torch (the wheel brings its own CUDA runtime
# libraries; the NVIDIA DRIVER comes from the GPU machine).
#
# Copy this folder to steps/gpu_check/ (see docs/gpu-steps.md). The platform builds it on push, like any step.
FROM python:3.11-slim
WORKDIR /app

# The GPU machines of the platform mount the NVIDIA driver under /usr/local/nvidia. The platform puts these two
# paths in front of the step's own values when the step runs there, so they are NOT needed on the platform's
# GPU machines. Keep them anyway: they make the same image work when you run it somewhere else (your own
# GPU workstation with the NVIDIA container runtime, another cluster). A python base has neither set, so
# without them torch cannot find the driver and silently trains on the CPU.
ENV LD_LIBRARY_PATH=/usr/local/nvidia/lib64:/usr/local/nvidia/lib
ENV PATH=/usr/local/nvidia/bin:${PATH}

# Pin torch: a floating version changes the CUDA runtime under you between two builds.
RUN pip install --no-cache-dir "torch==2.5.1" "PyYAML>=6,<7"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
