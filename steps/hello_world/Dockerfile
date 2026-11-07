# hello-world step image. The platform builds this on push and wires the
# resulting image into the WorkflowTemplate as image-hello-world. The in-image
# command is `python -m app.entry` — the same module you run locally.
FROM python:3.11-slim
WORKDIR /app
# kaos-lib, the platform library (datasets, run outputs; formerly the kubecore package), from
# github.com/kaos-io/kaos-lib. The platform's CI passes KAOS_LIB_PACKAGE, the WHOLE pip requirement (the
# platform registry's wheel); the default is this template's pin. Only app/ is copied into the image.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/67fa8e7ca231ea4c6015dc00d9afeada80f229d7.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
