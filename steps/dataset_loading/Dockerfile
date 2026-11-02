# dataset-loading step image: resolves the run's dataset choice to one commit.
FROM python:3.11-slim
WORKDIR /app
# The kubecore PACKAGE (datasets, run outputs), pinned to a commit. It shares the import
# name `kubecore` with the vendored engine at the repo root, which is NOT copied into
# step images: only app/ is. Bump the commit to take a newer package.
ARG KUBECORE_PKG_COMMIT=0136a205a82fbe4ed4a82037329e048f58e7e740
RUN pip install --no-cache-dir \
    "kubecore[zitadel] @ https://github.com/novelcore/hera-pipeline-template/archive/${KUBECORE_PKG_COMMIT}.zip#subdirectory=packages/kubecore"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
