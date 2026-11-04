"""Where a pipeline's outputs go: the app's own lakeFS outputs repository.

Platform-side naming only (the render-time engine reads the pipeline-context and
must stay stdlib + PyYAML). Steps write results with the `kaos_lib` Python package
(`kaos_lib.outputs.run`), which uses the same names: `outputs-<app>`, on
`main`, under `<kind>/<experiment>/<run>/`, one commit per producing step per run.

The enhancer injects CHECKPOINT_BUCKET (= the repository) and CHECKPOINT_PREFIX
(= `main/checkpoints`, the `{branch}/{path}` form S3-style readers use) and mirrors
them in `platform.checkpoints.*`.
"""

OUTPUTS_REPO_PREFIX = "outputs-"
OUTPUTS_REF = "main"  # the branch results land on (merged from a per-run branch)
CHECKPOINTS_DIR = "checkpoints"


def outputs_repo(ctx: dict) -> str:
    """The app's outputs repository name: `outputs-<app>`."""
    app = ctx.get("app")
    if not app:
        raise ValueError("context is missing 'app' - cannot derive the outputs repository")
    return f"{OUTPUTS_REPO_PREFIX}{app}"


def checkpoint_prefix() -> str:
    """`{branch}/checkpoints`: the key prefix (first segment = branch) a reader appends `<experiment>/<run>/` to."""
    return f"{OUTPUTS_REF}/{CHECKPOINTS_DIR}"
