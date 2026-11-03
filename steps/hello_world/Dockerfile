# hello-world step image. The platform builds this on push and wires the
# resulting image into the WorkflowTemplate as image-hello-world. The in-image
# command is `python -m app.entry` — the same module you run locally.
FROM python:3.11-slim
WORKDIR /app
# kaos-lib (datasets, run outputs; formerly the kubecore package). The PLATFORM picks it:
# the CI passes --build-arg KAOS_LIB_PACKAGE=<requirement> on every build, inside the
# range in .kaos/compat.yaml (docs/kaos-lib-versions.md). The value is the whole pip
# requirement (name, extras, version or URL), so the platform can move it to a kaos-lib
# release with no change here. This default is only for a build on your computer: until
# kaos-lib's first release it is a commit of hera-pipeline-template, where the package is
# still named `kubecore`. It shares the import name `kubecore` with the vendored engine at
# the repo root, which is NOT in this image: only app/ is copied.
ARG KAOS_LIB_PACKAGE="kubecore[zitadel] @ https://github.com/novelcore/hera-pipeline-template/archive/0136a205a82fbe4ed4a82037329e048f58e7e740.zip#subdirectory=packages/kubecore"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
