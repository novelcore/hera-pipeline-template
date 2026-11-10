"""Your pipeline: the DAG. Structure and nothing else.

Each step declares its name, the config sections it reads (reads=), whether it
needs a GPU (gpu=True), what it depends on (needs=), any small result files it
writes (outputs=), and an optional condition (when=). Every tunable parameter
lives in the config/ tree and reaches the submit form automatically — there is
no parameter wiring here.

This template ships one example step: hello-world reads the run's dataset (the
`dataset` parameter, <dataset-repo>@<version>) and writes a result to the app's
outputs repository. The platform pins every dataset of a run to one commit before the
first step starts, so no step pins data. Add your own steps under steps/<name>/ and
wire them here. See README.md / DEVELOPER.md.
"""

from pathlib import Path

from kubecore.authoring import pipeline, step  # the platform's engine provides this

HERE = Path(__file__).parent

# The name you pass here is for local readability only — the platform RENAMES
# the released WorkflowTemplate to "{your-app}-pipeline" at CI render time, so
# each app gets its own uniquely-named WFT (no collisions across apps in a
# shared namespace). You don't need to change it per app.
with pipeline("ml-pipeline") as p:
    hello = step("hello-world", reads=["experiment", "dataset"])
    # A GPU step: copy examples/gpu_check to steps/gpu_check, then uncomment (docs/gpu-steps.md).
    # gpu_check = step("gpu-check", reads=["experiment"], gpu=True)

if __name__ == "__main__":
    p.write(HERE / "out" / "raw-workflow-template.yaml")
