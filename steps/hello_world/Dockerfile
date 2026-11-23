# hello-world step image. The platform builds it on every push and runs `python -m app.entry`: the same
# module `kaosctl step run hello-world` runs on your machine.
FROM python:3.11-slim
WORKDIR /app
# kaos-lib, the platform library (github.com/kaos-io/kaos-lib). The platform's build passes KAOS_LIB_PACKAGE,
# the WHOLE pip requirement of the version it chose; there is no default: a local
# build passes it, or use `kaosctl step run` / `kaosctl dev`, which take your platform's choice. Add your own dependencies with a RUN pip install line of their own. The MLflow client comes with kaos-lib: add no line for it and pin no mlflow of your own.
ARG KAOS_LIB_PACKAGE=""
RUN test -n "${KAOS_LIB_PACKAGE}" || { echo "pass --build-arg KAOS_LIB_PACKAGE, or use kaosctl step run / kaosctl dev, which take your platform's choice" >&2; exit 1; }
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
