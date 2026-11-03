# 3. Your tools

**Goal:** every tool you need today is open in a browser tab and you are signed in to each.

**Who can do it:** anyone on a project team. What you may do in each tool depends on your role
([chapter 1](1-youre-in.md)).

## Open them from the console

You never need to type an address. Console → **Pipelines** → your app's row has a link to each tool:

| tool | console link | what you do there |
|---|---|---|
| **Argo Workflows** | **Run** (the form), **Runs in Argo**, **CI builds** | submit runs, watch them, read logs, retry; see the builds of your pipeline |
| **lakeFS** (your project's data store) | **Datasets**, then *Create in project (opens its lakeFS)*; **Outputs** | datasets: create, upload, pull requests, **Release version**; your runs' outputs in `outputs-<app>` |
| **MLflow** | **MLflow**, **Models** | metrics, parameters and artifacts of runs; compare runs; registered models |
| **Console Datasets page** | sidebar → **Datasets** | every dataset of the organisation, its versions and location; **sharing** with other projects |
| **GitHub** | the app page | your code, pull requests and the `wft-render` / `kubecore-ml-ci` checks |

Each tool signs you in with the same KAOS account. If a tool asks you to sign in, use the same
account as for the console.

## The addresses, if you want bookmarks

| tool | address |
|---|---|
| Argo Workflows | `https://workflows.system.<pool domain>` |
| lakeFS | `https://lakefs-<project>.<project domain>` |
| MLflow | `https://mlflow-<project>.<project domain>` |
| console | `https://<org>.console.<platform domain>` |

The pool domain is the domain of the cluster your project runs on. The project domain is your
project's subdomain under it (on the development platform it has the form
`<project>.<region>.<pool domain>`, for example `europe-west1`; verify on yours). The console links
are always right, so copy the address from there.

## What you should see

- **Argo:** the **Workflow Templates** list has `<app>-pipeline` once the first build is done.
  **Workflows** lists runs and builds.
- **lakeFS:** the **Datasets** page lists `dataset-default` and any datasets of your project, with
  a **New dataset** button. The repository list also has `outputs-<app>`.
- **MLflow:** the **Experiments** list. It is empty until a step logs a run.
- **Console Datasets:** your project's datasets, with filters for project and location.

## If it isn't there

- **A link is missing from the app's row:** that part of the project is not deployed yet. For
  example, no **MLflow** link means the project has no MLflow. Ask your platform contact.
- **"403" or "access denied" in Argo:** your role does not include this project. Check your team
  ([chapter 1](1-youre-in.md)).
- **No `<app>-pipeline` in Argo:** the first build has not finished ([chapter 2](2-your-apps.md)).

**Next:** [4. Install kaosctl and sign in](4-install-kaosctl.md).
