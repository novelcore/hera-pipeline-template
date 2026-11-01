# dataset-loading step image: resolves the run's dataset choice to one commit.
FROM python:3.11-slim
WORKDIR /app
# The kubecore PACKAGE (datasets, run outputs), pinned to a commit. It shares the import
# name `kubecore` with the vendored engine at the repo root, which is NOT copied into
# step images: only app/ is. Bump the commit to take a newer package.
ARG KUBECORE_PKG_COMMIT=5e718a1e957bc9c5a1d6c13c12afe687e91d05b1
RUN pip install --no-cache-dir \
    "https://github.com/novelcore/hera-pipeline-template/archive/${KUBECORE_PKG_COMMIT}.zip#subdirectory=packages/kubecore"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
