# hello-world step image. The platform builds this on push and wires the
# resulting image into the WorkflowTemplate as image-hello-world. The in-image
# command is `python -m app.entry` — the same module you run locally.
FROM python:3.11-slim
WORKDIR /app
# The kubecore PACKAGE (datasets, run outputs), pinned to a commit. It shares the import
# name `kubecore` with the vendored engine at the repo root, which is NOT copied into
# step images: only app/ is. Bump the commit to take a newer package.
ARG KUBECORE_PKG_COMMIT=819920b6d73e0fe48db1cbd5643636cb07b57209
RUN pip install --no-cache-dir \
    "https://github.com/novelcore/hera-pipeline-template/archive/${KUBECORE_PKG_COMMIT}.zip#subdirectory=packages/kubecore"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
