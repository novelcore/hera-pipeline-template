# Guide: add a step that reads a dataset and writes a result

**Goal:** a new step, `count-files`, that reads the dataset version the run picked, counts its
files, and writes the count as a report. It is checked on a pull request, built on merge,
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
"""count-files: count the files of the run's dataset and save the count as a report."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    data = step.input("dataset")  # a folder: the dataset version the run picked
    count = sum(1 for f in data.rglob("*") if f.is_file() and not f.name.startswith("."))
    print(f"[count-files] {count} files", flush=True)
    report = step.output("file-count")  # a folder to write into; saved by step.result()
    (report / "count.txt").write_text(f"{ctx.experiment}: {count} files\n")
    step.result(files=count)


if __name__ == "__main__":
    main()
```

- `step.input("dataset")` is a folder with the files of the dataset. Which version it holds was chosen on the
  run form; the code never names a version ([How steps use datasets](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/steps-and-datasets.html)).
- `step.output("file-count")` is an empty folder. What it holds when `step.result()` runs is saved.
- `step.result(files=count)` saves the report and hands `files` to any step that needs this one.

## 3. The Dockerfile: `steps/count_files/Dockerfile`

Copy the `ARG` line from `steps/hello_world/Dockerfile`, keeping its value:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
ARG KAOS_LIB_PACKAGE="<copy the value from steps/hello_world/Dockerfile>"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
```

Keep the name `KAOS_LIB_PACKAGE`. The platform's build passes its kaos-lib through it
([who picks the version](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/support-window.html#in-a-pipeline-who-picks-the-version)). Copy only `app/`.

## 4. One line in `pipeline.py`

```python
    hello = step("hello-world", kind="evaluate", needs=[prepare], produces=[artifact("report")])
    count = step("count-files", kind="evaluate", inputs=["dataset"], produces=[artifact("file-count")])
```

- `inputs=["dataset"]` names the setting in `config/` that holds the dataset: `dataset: "dataset-default"` in
  `config/dataset.yaml`. The name in `step.input("dataset")` is this name.
- `produces=[artifact("file-count")]` names what the step writes. The name in `step.output("file-count")` is
  this name. Choose a name no other step of the pipeline produces.

The step needs no other step, so it runs alongside `prepare`.

To read a second dataset, add a setting (`labels: "dataset-labels"` in a file of `config/`), name it in
`inputs=["dataset", "labels"]`, and call `step.input("labels")`.

## 5. Check it locally

```bash
kaosctl lint
kaosctl step run count-files --input dataset=./a-folder-with-a-few-files
```

**You should see** no errors from `kaosctl lint`, then the step's own output, its result and where the report
was kept on your machine. A name in `inputs=` that is not a setting fails the check with the same message the
platform gives ([Check your pipeline](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/lint.html), [Run a step locally](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/step-run.html)).

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

**You should see** a `count-files` box. Its log says `N files`, and
`outputs-<app>` has `file-count/<experiment>/<run>/count.txt`.

## If it isn't there

- `wft-render` names the problem: see [When things go wrong](cookbook/10-when-things-go-wrong.md#the-pull-request-checks).
- `ModuleNotFoundError: kaos_lib` in the step log: the Dockerfile does not install `KAOS_LIB_PACKAGE`.
- `'dataset' is not an input of step 'count-files'`: the name is missing from `inputs=` in `pipeline.py`.
- `step 'count-files' ended without step.result()`: `step.result()` must be the last call of the step.
- The dataset holds no files yet: the step stops and says so. Push your data first ([First dataset and run](first-run.md)).

**Next:** [Run on a released version and find the result](guide-run-on-a-version.md).
