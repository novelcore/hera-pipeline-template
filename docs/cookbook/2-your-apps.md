# 2. Your project's apps

**Goal:** you have an ML app to work in, cloned on your computer.

**Who can do it:** finding and cloning an app needs `dev`, `ops` or `admin` on the project. Creating
an app is done in the console, by someone the console lets create apps in that project (verify for
your organisation; usually a project `admin` or `ops`).

## What an ML app is

An **ML app** is one pipeline with its own code. Creating an app gives you:

| what | name | what it is for |
|---|---|---|
| a GitHub repository | `<app>`, in your organisation's GitHub organisation | your code: `pipeline.py`, `config/`, `steps/`, seeded from a template |
| a pipeline | `<app>-pipeline`, an Argo WorkflowTemplate | the run form you submit ([chapter 7](7-run-it.md)) |
| an outputs repository | `outputs-<app>`, in your project's lakeFS | everything your runs write ([chapter 8](8-results-and-weights.md)) |
| CI on the repository | the checks `wft-render` (pull requests) and `kubecore-ml-ci` (builds) | every merge into `dev` builds a new pipeline version ([chapter 6](6-your-pipeline.md)) |

The project already has a dataset called **`dataset-default`**, which belongs to the project and
not to the app. It starts empty. All the apps of a project share the project's datasets, its
lakeFS and its MLflow.

## If your project already has apps

1. Console → **Pipelines**. Each row is one ML app. It shows the project, the status of its first
   build, and a **Run** button with links: **Runs in Argo**, **CI builds**, **MLflow**, **Outputs**,
   **Models**, **Datasets** and **App settings**.
2. Open your app. Its page links the GitHub repository.
3. Clone it. You need `git`, an editor, and access to the repository, which your project team
   gives you ([chapter 1](1-youre-in.md)). Docker is optional, for building a step image on your
   own computer; the platform builds every image for you.

    ```bash
    git clone https://github.com/<github-org>/<app>.git
    cd <app>
    git checkout dev
    ```

Work on the **`dev`** branch. The platform builds from it, and pull requests into it are checked.

## If it has none: create one

1. Console → **Pipelines** → **New pipeline**. *New pipeline* offers only the ML pipeline templates,
   and only the projects that can host an ML pipeline.
2. Pick a template card. This template, hera, gives you an empty scaffold: `dataset-loading` and
   one example step. The yolo template is a ready YOLO training pipeline
   ([chapter 9](9-the-yolo-use-case.md)). The cards are named as your platform's catalog names
   them (verify the names in your console).
3. Follow the wizard. It asks which project the app belongs to and what to call it, and offers
   sensible defaults for the rest.
4. Create it.

## What you should see, and how long it takes

The repository and the outputs repository appear first, usually within minutes. Then the first
pipeline build runs. Your app's row and its **First pipeline build** card go through these states:

| status | what it means |
|---|---|
| **Awaiting first build** | the repository exists and the build has not started |
| **Building** | `kubecore-ml-ci` is building the step images and the pipeline; **View run** opens it in Argo |
| **Ready** ("Pipeline ready") | the pipeline exists and you can submit it |
| **Build failed** | open **View run** and read the failing step ([chapter 10](10-when-things-go-wrong.md)) |

The status comes from the app's `PipelineReady` condition. A first build takes several minutes,
most of it building the step images. You can create and upload a dataset before the build is done
([chapter 5](5-your-data.md)).

!!! warning "Ignore the upload command on the build card"
    The **First pipeline build** card shows `python3 scripts/upload-dataset.py <folder> [name]`.
    That script is not in the templates any more. Upload with `kaosctl` instead
    ([chapter 5](5-your-data.md)).

## If it isn't there

- **No New pipeline button, or your project is not offered:** the project has no ML stack, so it
  cannot host an ML pipeline. Ask a project admin to enable it.
- **Stuck on Awaiting first build:** the build has not been triggered. Check the repository's
  `dev` branch exists, then ask your platform contact.
- **No repository in GitHub:** you are not on a project team yet ([chapter 1](1-youre-in.md)).

**Next:** [3. Your tools](3-your-tools.md).
