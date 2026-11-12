# hello-world step image. The platform builds it on every push and runs `python -m app.entry`: the same
# module `kaosctl step run hello-world` runs on your machine.
FROM python:3.11-slim
WORKDIR /app
# kaos-lib, the platform library (github.com/kaos-io/kaos-lib). The platform's build passes KAOS_LIB_PACKAGE,
# the WHOLE pip requirement of the version it chose; the default below is what a local build installs
# (kaos-lib 0.5.0). Add your own dependencies with a RUN pip install line of their own.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/036b6f401fdc7830cdbceaabb899d8512f85f040.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
