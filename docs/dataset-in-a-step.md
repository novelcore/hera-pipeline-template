# Use a dataset in a step

**Goal:** a step that reads exactly the dataset version the run picked. The template's
`steps/hello_world/` does this; copy it.

## 1. Let the step read the run's dataset

In `pipeline.py`, a step that reads the dataset lists the `dataset` section:

```python
mine = step("my-step", reads=["experiment", "dataset"])
```

You write no pinning code. Before the first step starts, the platform pins every dataset of the run to one
commit and gives each step that choice; kaos-lib's `datasets.materialize` reads that commit, so a `latest` that
moves during the run changes nothing. `datasets.resolve(ref)` returns the same commit, if you want to record it.

## 2. Install kaos-lib in the step image

In `steps/my_step/Dockerfile`, copy these lines from `steps/hello_world/Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
ARG KAOS_LIB_PACKAGE="<the requirement in steps/hello_world/Dockerfile>"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}" PyYAML
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
```

Keep the name `KAOS_LIB_PACKAGE`: the platform's build passes its own kaos-lib version through it,
so your step moves with the others ([kaos-lib versions](kaos-lib-versions.md)).

## 3. Read the dataset

```python
import argparse, yaml
from kaos_lib import datasets
from kaos_lib.errors import EmptyDataset

parser = argparse.ArgumentParser()
parser.add_argument("--params", required=True)
args, _ = parser.parse_known_args()
cfg = yaml.safe_load(args.params)

ref = datasets.DatasetRef.parse(cfg["dataset"])
try:
    entry = datasets.materialize(ref)    # yolo: the path of data.yaml; no layout: the folder
except EmptyDataset:
    entry = None                         # the dataset has no files yet (a new dataset-default)
```

| the dataset's layout | `materialize` returns |
|---|---|
| `yolo` | the local `data.yaml`, its `path:` pointing at the downloaded images and labels |
| none | the local folder with the files at that commit (`prefix=` for one folder) |

The address of lakeFS and the credentials come from the step's environment: you write none of that.
The first call downloads and keeps the copy; on HPC the platform has staged it already.

Catch `EmptyDataset` only in a step that can do something useful without data (the template's
`hello-world` reports "holds no files yet" and still succeeds). A training step should let it fail.

**Next:** [Write results from a step](write-a-step.md).
