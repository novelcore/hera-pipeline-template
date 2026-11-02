# hello-world step image. The platform builds this on push and wires the
# resulting image into the WorkflowTemplate as image-hello-world. The in-image
# command is `python -m app.entry` — the same module you run locally.
FROM python:3.11-slim
WORKDIR /app
# kaos-lib (datasets, run outputs; formerly the kubecore package). The PLATFORM picks
# its version: the CI passes --build-arg KAOS_LIB_PACKAGE=<spec> on every build, inside
# the range in .kaos/compat.yaml (docs/kaos-lib-versions.md). This default is only for a
# build on your computer. Until kaos-lib's first release the default is a commit of
# this repository, whose package is still named `kubecore`, hence the name below. It
# shares the import name `kubecore` with the vendored engine at the repo root, which is
# NOT copied into step images: only app/ is.
ARG KAOS_LIB_PACKAGE="@ https://github.com/novelcore/hera-pipeline-template/archive/0136a205a82fbe4ed4a82037329e048f58e7e740.zip#subdirectory=packages/kubecore"
RUN pip install --no-cache-dir "kubecore[zitadel] ${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
