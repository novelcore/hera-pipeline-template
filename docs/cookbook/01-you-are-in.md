# 1. You are in

You were given a KAOS account and added to a project. This page shows what you see after you sign in.

## Do this

1. Open the KAOS console link you were sent and sign in.
2. In the left sidebar, find the **Machine learning** section.

## You should now see

The **Machine learning** section has four pages:

| Page | What it is for |
|---|---|
| **Pipelines** | The training pipelines of your project, and the **New pipeline** button. Each pipeline has a link to its run page. |
| **Datasets** | The datasets of your project, their versions, and an **Open in lakeFS** link for each. |
| **Models** | The models your runs produced. |
| **Machines** | The kinds of machine your pipelines can run on. |

Each of these pages has a short guide. Open **Settings**, then **Guides**, for the same guides in one place.

!!! note "Words used in this guide"
    - **Project**: the space your team works in. Your pipelines, datasets and models belong to it.
    - **Pipeline**: your training workflow, a list of steps such as "prepare data" then "train".
    - **Dataset**: a named set of files with numbered versions.
    - **Version**: a frozen copy of a dataset, written `v1`, `v2`, and so on.
    - **Run form**: the page where you pick settings and a dataset version and press Submit to start a run.
    - **lakeFS**: the storage that holds your datasets and your run outputs. You reach it from the console with **Open in lakeFS**.
    - **MLflow**: the page that records each run's settings, metrics and models.

If a page is empty, that is normal for a new project. If you cannot see **Machine learning** at all, ask your project administrator to add you to the project.

Next: [your project and where pipelines run](02-your-project.md).
