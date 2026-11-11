# 2. Your project's apps

**Goal:** you have an ML app to work in, cloned on your computer.

**Who can do it:** finding and cloning an app needs `dev`, `ops` or `admin` on the project. Creating
an app is done in the console, by someone the console lets create apps in that project (verify for
your organisation; usually a project `admin` or `ops`).

## What an ML app is

An **ML app** is one pipeline with its own code. Creating one gives you:

| what | name | what it is for |
|---|---|---|
| a code repository on GitHub | `<app>` | your code: `pipeline.py`, `config/`, `steps/`, started from a template |
| a pipeline | `<app>-pipeline` | the run form you submit ([chapter 7](7-run-it.md)) |
| a results repository in lakeFS | `outputs-<app>` | everything your runs write ([chapter 8](8-results-and-weights.md)) |
| automatic checks | `wft-render` on pull requests, `kubecore-ml-ci` on merges | every merge into `dev` builds a new version of the pipeline ([chapter 6](6-your-pipeline.md)) |

The project already has a dataset called **`dataset-default`**. It belongs to the project, not to
one pipeline, and it starts empty. All the pipelines of a project share its datasets, its lakeFS
(your data storage) and its MLflow (where runs record their results).

## If your project already has apps

1. Console → **Pipelines**. Each row is one ML app. It shows the project, the status of its first
   build, and a **Run** button and a **⋯** menu of links: the runs link (the first entry), **CI builds**, **MLflow**, **Outputs**,
   **Models**, **Datasets** and **App settings**.
2. Open your app. Its page links the GitHub repository.
3. Clone it. You need `git`, an editor, and access to the repository, which your project team
   gives you ([chapter 1](1-youre-in.md)). Docker is optional, for building a step image on your
   own computer; KAOS builds every image for you.

    ```bash
    git clone https://github.com/<github-org>/<app>.git
    cd <app>
    git checkout dev
    ```

Work on the **`dev`** branch. New versions of your pipeline are built from it, and pull requests into it are checked.

## If it has none: create one

1. Console → **Pipelines** → **New pipeline**. *New pipeline* offers only the ML pipeline templates,
   and only the projects that can host an ML pipeline.
2. Pick a template card. This template, hera, gives you an empty scaffold: one example step. The yolo template is a ready YOLO training pipeline
   ([chapter 9](9-the-yolo-use-case.md)). The cards carry the names you see in your console.
3. Follow the wizard. It asks which project the app belongs to and what to call it, and offers
   sensible defaults for the rest.
4. Create it.

## What you should see, and how long it takes

The repository and the outputs repository appear first, usually within minutes. Then the first
pipeline build runs. Your app's row and its **First pipeline build** card go through these states:

| status | what it means |
|---|---|
| **Awaiting first build** | the repository exists and the build has not started |
| **Building** | `kubecore-ml-ci` is building the step images and the pipeline; **View run** opens it |
| **Ready** ("Pipeline ready") | the pipeline exists and you can submit it |
| **Build failed** | open **View run** and read the failing step ([chapter 10](10-when-things-go-wrong.md)) |

A first build takes several minutes,
most of it building the step images. You can create and upload a dataset before the build is done
([chapter 5](5-your-data.md)).

## If it isn't there

- **No New pipeline button, or your project is not offered:** the project is not set up for ML pipelines yet. Ask a project admin to enable it.
- **Stuck on Awaiting first build:** the build has not been triggered. Check the repository's
  `dev` branch exists, then ask your KAOS contact.
- **No repository in GitHub:** you are not on a project team yet ([chapter 1](1-youre-in.md)).

**Next:** [3. Your tools](3-your-tools.md).
