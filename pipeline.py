"""Your pipeline: the steps, what each one reads and writes, and their order. Nothing else.

This template ships two example steps:

  prepare      reads the run's dataset (the `dataset` setting in config/) and writes a new version of the
               dataset `clean`: the files of at least `prepare.min_bytes` bytes.
  hello-world  reads exactly the version `prepare` wrote in this run and writes a small report.

Every setting lives in config/ and reaches the run form by itself. The version of each dataset is chosen on
the run form, never here. Add your own steps under steps/<name>/ and declare them below
(https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/first-step.html).
"""

from pathlib import Path

from kubecore.authoring import artifact, dataset, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    prepare = step("prepare", kind="transform", reads=["prepare"], inputs=["dataset"],
                   produces=[dataset("clean")])
    hello = step("hello-world", kind="evaluate", needs=[prepare], produces=[artifact("report")])
    # A GPU step: copy examples/gpu_check to steps/gpu_check, then uncomment
    # (https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/bigger-machines.html).
    # gpu_check = step("gpu-check", kind="train", reads=["experiment"], gpu=True)

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
