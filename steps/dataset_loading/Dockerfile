# dataset-loading step image: resolves the run's dataset choice to one commit.
FROM python:3.11-slim
WORKDIR /app
# kaos-lib, the platform library (datasets, run outputs; formerly the kubecore package), from
# github.com/kaos-io/kaos-lib. The platform's CI passes KAOS_LIB_PACKAGE, the WHOLE pip requirement (the
# platform registry's wheel); the default is this template's pin. Only app/ is copied into the image.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/dc24f292029bb2a49a2cdf5c24eb169d7706d9a5.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
