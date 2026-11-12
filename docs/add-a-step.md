# Add a step

This is the main page. Follow it top to bottom. By the end you will have a brand new step in your pipeline.

We will add a step called **`say-goodbye`**. It runs after the step that ships with the template. Swap in your own name and your own code once you are comfortable.

!!! warning "The naming rule. Read this once."
    A step has two names and they look slightly different.

    - The step name uses dashes. Example: `say-goodbye`.
    - The folder name uses underscores. Example: `steps/say_goodbye`.

    Same word. One uses dashes, the other uses underscores. Get this right and everything else falls into place. The platform matches them for you.

## What you will touch

Only these. Nothing else.

| File | Why |
|---|---|
| `steps/say_goodbye/app/entry.py` | the code your step runs |
| `steps/say_goodbye/app/__init__.py` | an empty file that marks a Python package |
| `steps/say_goodbye/Dockerfile` | how your step gets packed into a box |
| `pipeline.py` | one line that adds the step to the list |

Your app holds no copy of the platform's pipeline engine, so there is nothing else to leave alone.

## Step 1. Make the folder

Open your Terminal. Move into the project folder if you are not already there. Then run these two lines.

```bash
mkdir -p steps/say_goodbye/app
touch steps/say_goodbye/app/__init__.py
```

The first line makes the folders. The second makes an empty file called `__init__.py`. Leave that file empty. It just tells Python this is a package.

![The new say_goodbye folder in the sidebar, with entry.py open](img/new-step-folder.png)

## Step 2. Write the code

Create a file at `steps/say_goodbye/app/entry.py`. In Visual Studio Code, right click the `app` folder, choose New File, and name it `entry.py`.

Paste this in exactly.

```python
"""say-goodbye: print a goodbye with the number of files hello-world counted."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    files = step.upstream("hello-world").values["files"]
    print(f"[say-goodbye] goodbye from {ctx.experiment}: hello-world counted {files} files")
    step.result()


if __name__ == "__main__":
    main()
```

What this does, in plain words.

- `step.start()` is always the first line. It gives you the run: its experiment (`ctx.experiment`), its name (`ctx.run`) and your settings (`ctx.params`).
- `step.upstream("hello-world")` is the result of the step before yours. `hello-world` ends with `step.result(files=...)`, so `values["files"]` is that number.
- `step.result()` is always the last line. It tells the platform the step is done. A step that ends without it fails.

That is a fine first step. Replace the print with your real work later.

!!! note "Where do settings come from?"
    Name a section of your `config/` folder in `reads=` (Step 4) and it arrives in `ctx.params`, like `ctx.params["experiment"]`. A step takes no arguments and reads no environment variables. It is all handed to you by `step.start()`. The six calls a step can make are on one page: [The step API](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/step.html).

## Step 3. Write the Dockerfile

Create a file at `steps/say_goodbye/Dockerfile`. No file extension. Just `Dockerfile`.

Copy `steps/hello_world/Dockerfile` and change nothing in it but the comment at the top:

```bash
cp steps/hello_world/Dockerfile steps/say_goodbye/Dockerfile
```

```dockerfile
FROM python:3.11-slim
WORKDIR /app
ARG KAOS_LIB_PACKAGE="<the value in steps/hello_world/Dockerfile>"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
```

Keep the name `KAOS_LIB_PACKAGE`: the platform's build passes the kaos-lib version through it ([who picks the version](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/support-window.html#in-a-pipeline-who-picks-the-version)). Add the Python packages your own code needs with a `RUN pip install` line of their own.

![The say_goodbye Dockerfile open in the editor](img/dockerfile.png)

That is the whole Dockerfile. The platform uses it to build your step into an image. You never write an image name. You never write a registry address. The platform does that part.

!!! warning "The most common mistake"
    People add the step to `pipeline.py` but forget the Dockerfile. The check on your request catches it and tells you exactly which file is missing. So you find out early, not in the middle of a run.

## Step 4. Add the step to your pipeline

Open `pipeline.py`. You will see something like this.

```python
with pipeline("ml-pipeline") as p:
    prepare = step("prepare", kind="transform", reads=["prepare"], inputs=["dataset"],
                   produces=[dataset("clean")])
    hello = step("hello-world", kind="evaluate", needs=[prepare], produces=[artifact("report")])
```

Add one line for your new step. Make it run after `hello-world` by pointing `needs` at it.

```python
    hello = step("hello-world", kind="evaluate", needs=[prepare], produces=[artifact("report")])
    goodbye = step("say-goodbye", kind="control", needs=[hello])
```

![pipeline.py with the new say-goodbye line added](img/pipeline-line.png)

Here is what each part means.

- `"say-goodbye"` is the step name. Dashes, remember.
- `kind="control"` says what the step is. Every step has a kind: `ingest`, `transform`, `train`, `evaluate`, `publish` or `control` ([what each one means](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/steps.html#what-you-declare)).
- `needs=[hello]` means run after the `hello` step, and lets your code ask for its result. This one line is how you set the order.

A step can declare three more things, and this one needs none of them: `reads=` (the sections of `config/` it gets), `inputs=` (the datasets it reads) and `produces=` (what it writes). The two steps above it show them, and [the guide](guide-step-with-data.md) adds a step that uses all three.

!!! note "A small ordering trap"
    `needs=[hello]` points at the `hello` line above it. So the step you depend on must be written above yours in the file. If you get it wrong you will see a clear error that names the missing word. Nothing breaks silently.

## Step 5. Check it on your computer (optional)

You do not need a cloud run to sanity check your work. From the project folder, run this.

```bash
kaosctl lint
kaosctl step run prepare --input dataset=./a-folder-with-a-few-files
kaosctl step run hello-world
kaosctl step run say-goodbye
```

`kaosctl lint` reads your files and names every mistake with its line ([Check your pipeline](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/lint.html)). It does not run the pipeline: that only happens later, from the web page. `kaosctl step run` runs one step on your computer the way the platform runs it. Run the steps in order: each one finds the result of the one before it ([Run a step locally](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/step-run.html)). If your step shows up with no errors, you are in good shape. If you made a typo, this tells you in plain words.

## You are done editing

That is the whole job. You made a folder, wrote a small program, wrote a Dockerfile, and added one line. 

Next you will send this in and watch it get checked. Go to [Send your change in and go live](send-it-in.md).

!!! tip "Need one step to hand data to the next?"
    Steps do not share a disk. A step hands on small values with `step.result(rows=1200)`, and the next step reads them with `step.upstream("<step>").values`. Files go into an output: the step declares it in `produces=`, writes into `step.output("<name>")`, and the next step reads it with `step.input("<name>")` ([Write results from a step](write-a-step.md)).

!!! tip "A step that reads the dataset"
    This page adds a step with no data. For one that reads a dataset and writes files, follow [the guide](guide-step-with-data.md).
