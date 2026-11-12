# hello-world step image. The platform builds it on every push and runs `python -m app.entry`: the same
# module `kaosctl step run hello-world` runs on your machine.
FROM python:3.11-slim
WORKDIR /app
# kaos-lib, the platform library (github.com/kaos-io/kaos-lib). The platform's build passes KAOS_LIB_PACKAGE,
# the WHOLE pip requirement of the version it chose; the default below is what a local build installs
# (kaos-lib 0.5.0). Add your own dependencies with a RUN pip install line of their own.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/kaos-lib/kaos_lib-0.5.0rc1-py3-none-any.whl#sha256=8c4977c0a49c0b8fa749d46f2c40735bc7c25786ff3c6f71bfaa56b87940b989"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
