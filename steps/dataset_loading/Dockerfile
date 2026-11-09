# dataset-loading step image: resolves the run's dataset choice to one commit.
FROM python:3.11-slim
WORKDIR /app
# kaos-lib, the platform library (datasets, run outputs; formerly the kubecore package), from
# github.com/kaos-io/kaos-lib. The platform's CI passes KAOS_LIB_PACKAGE, the WHOLE pip requirement (the
# platform registry's wheel); the default is this template's pin. Only app/ is copied into the image.
# Default for a local build: kaos-lib 0.4.0rc17. The platform's CI overrides it with --build-arg KAOS_LIB_PACKAGE.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/50aee081e1bb031ef199eefe68e62ee35e6281d7.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
