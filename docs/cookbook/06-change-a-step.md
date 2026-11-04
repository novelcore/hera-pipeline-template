# 6. Change a step and push

This page changes the example step so it reads your dataset. For a first look at the files, see [How it works](../how-it-works.md). For adding whole new steps, see [Add a step](../add-a-step.md).

## Do this

**1. Declare the dataset setting.** Create `config/dataset.yaml`:

```yaml
dataset: "dataset-default@latest"
```

and add `- dataset` under `- experiment` in `config/config.yaml`. The run form now has a **dataset** dropdown with your released versions. (Skip this if you started from the yolo template; it has it already.)

**2. Tell the step to read it.** In `pipeline.py`:

```python
hello = step("hello-world", reads=["experiment", "dataset"])
```

**3. Read the data in the step.** Add `kaos-lib` to `steps/hello_world/Dockerfile`:

```dockerfile
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel]==0.4.0rc10"
RUN pip install --no-cache-dir \
    --extra-index-url https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/simple/ \
    PyYAML "${KAOS_LIB_PACKAGE}"
```

Keep the name `KAOS_LIB_PACKAGE`: the platform replaces its value with the version it recommends when it builds your image. See [kaos-lib versions](../kaos-lib-versions.md).

In `steps/hello_world/app/entry.py`:

```python
from kaos_lib import datasets

ref = datasets.DatasetRef.parse(cfg["dataset"])   # e.g. "dataset-cats@v1"
data = datasets.materialize(ref)                  # yolo: path of data.yaml; raw: the folder
print("commit", datasets.resolve(ref), "data at", data)
```

`materialize` downloads that version once and reuses it. On the platform the credentials are already there; on your laptop it uses your `kaosctl login`.

**4. Check it on your laptop** (no cloud needed):

```bash
./run.sh
```

**5. Push.**

```bash
git checkout -b read-dataset
git add -A && git commit -m "read the dataset"
git push -u origin read-dataset
```

Open the pull request GitHub offers, wait for the green check, and merge it. [Send your change in](../send-it-in.md) and [Go live](../go-live.md) show each screen.

## You should now see

- `./run.sh` finishes without an error.
- A green tick on your pull request, then a green tick on the merge a few minutes later. Your pipeline is now ready to run.

Next: [run it](07-run-it.md).
