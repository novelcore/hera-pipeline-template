# dataset-loading step image: resolves the run's dataset choice to one commit.
FROM python:3.11-slim
WORKDIR /app
# kaos-lib, the platform library (datasets, run outputs), from
# github.com/kaos-io/kaos-lib. The platform's CI passes KAOS_LIB_PACKAGE, the WHOLE pip requirement (the
# platform registry's wheel); the default is this template's pin. Only app/ is copied into the image.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/465416af8f0730a3d9f690c89fcb4943d301fcdb.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
