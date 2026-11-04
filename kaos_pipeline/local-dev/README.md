# kaos_pipeline/local-dev — stand-ins for LOCAL rendering only

These files let `./run.sh` render, enhance and compose on a laptop with no connection to the
platform. **You do not own or edit them.** On a release the platform provides the real versions:

- `pipeline-context.yaml` — what the enhancer needs to know about your project (compute
  classes, MLflow and lakeFS endpoints, secret names, results location).

The values here are **non-functional placeholders** (`PLACEHOLDER-*`, `*.internal.invalid`).
Real endpoints and names are filled in by the platform when it releases your pipeline and are
never committed to a repository. A local render shows the correct *shape*; the release always
uses the real values.
