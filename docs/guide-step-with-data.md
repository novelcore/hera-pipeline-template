# Guide: add a step that reads the dataset and writes a result

**Goal:** a new step, `count-files`, that reads the dataset version the run picked, counts its
files, and writes the count to `outputs-<app>`. It is checked on a pull request, built on merge,
and run from the form.

**You need:** your app cloned on `dev` ([chapter 2](cookbook/2-your-apps.md)); role `dev`, `ops` or
`admin`.

## 1. The folder

The step name uses dashes and its folder uses underscores.

```bash
mkdir -p steps/count_files/app
touch steps/count_files/app/__init__.py
```

## 2. The code: `steps/count_files/app/entry.py`

```python
"""count-files: count the files of the run's dataset and write the count as a result."""
import argparse, json, os, tempfile
from pathlib import Path

import yaml
from kaos_lib import datasets, outputs
from kaos_lib.errors import EmptyDataset

READS = ["experiment", "dataset"]          # must match reads= in pipeline.py


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)          # the composed config/
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params)

    # The platform pinned the run's dataset to one commit; materialize reads that commit, not the moving pick.
    ref = datasets.DatasetRef.parse(cfg["dataset"])
    commit = datasets.resolve(ref)
    try:
        entry = datasets.materialize(ref)                     # yolo: data.yaml; no layout: a folder
        root = entry.parent if entry.is_file() else entry
        count = sum(1 for p in root.rglob("*") if p.is_file())
    except EmptyDataset:
        count = 0
    print(f"[count-files] {cfg['dataset']} @ {commit}: {count} files")

    # Write the result: one merge commit in outputs-<app> under checkpoints/<experiment>/<run>/.
    app, run = os.environ["CHECKPOINT_BUCKET"], os.environ["KUBECORE_RUN_ID"]
    with tempfile.TemporaryDirectory() as tmp, outputs.run(app, cfg["experiment"]["name"], run) as r:
        (Path(tmp) / "count.json").write_text(json.dumps({"dataset": cfg["dataset"], "files": count}))
        r.save(tmp)
        print("[count-files] committed", r.finish({"dataset_ref": cfg["dataset"],
                                                    "dataset_commit": commit}))


if __name__ == "__main__":
    main()
```

## 3. The Dockerfile: `steps/count_files/Dockerfile`

Copy the `ARG` line from `steps/hello_world/Dockerfile`, keeping its value:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
ARG KAOS_LIB_PACKAGE="<copy the value from steps/hello_world/Dockerfile>"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}" PyYAML
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
```

Keep the name `KAOS_LIB_PACKAGE`. The platform's build passes its kaos-lib through it
([kaos-lib versions](kaos-lib-versions.md)). Copy only `app/`.

## 4. One line in `pipeline.py`

```python
with pipeline("ml-pipeline") as p:
    hello = step("hello-world", reads=["experiment", "dataset"])
    count = step("count-files", reads=["experiment", "dataset"])
```

It runs alongside `hello-world`.

## 5. Check it locally

```bash
kaosctl render --context pipeline-context.yaml
kaosctl step run count-files
```

**You should see** `out/raw-workflow-template.yaml` with a `count-files` task, then the step's own
output. A typo in `reads=` fails the render with the same message the platform gives
([Check and try a step on your computer](check-and-try-locally.md)).

## 6. Pull request, merge, run

```bash
git checkout -b add-count-files dev
git add steps/count_files pipeline.py
git commit -m "add count-files step"
git push -u origin add-count-files
```

Open a pull request into `dev`. Wait for **`wft-render`** to go green, then merge. Wait for
**`kubecore-ml-ci`** to go green. Then submit the pipeline with a released dataset
([Run it](cookbook/7-run-it.md)).

**You should see** a `count-files` box. Its log says `<dataset> @ <commit>: N files`, and
`outputs-<app>` has `checkpoints/<experiment>/<run>/count.json`.

## If it isn't there

- `wft-render` names the problem: see [When things go wrong](cookbook/10-when-things-go-wrong.md#the-pull-request-checks).
- `ModuleNotFoundError: kaos_lib` in the step log: the Dockerfile does not install `KAOS_LIB_PACKAGE`.
- Both `hello-world` and `count-files` write to the same folder. Each makes its own commit, and
  their files sit side by side.

**Next:** [Run on a released version and find the result](guide-run-on-a-version.md).
