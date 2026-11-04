# Send your change in and go live

You changed some files on your computer. To get them into the pipeline you open a **pull request**
into `dev`, wait for the check, and merge. The merge builds a new version of your pipeline.

A pull request changes nothing on its own. It is a proposal, and the platform checks it first.

## 1. Branch, commit, push

```bash
git checkout dev && git pull
git checkout -b add-say-goodbye
git add .
git commit -m "add say-goodbye step"
git push -u origin add-say-goodbye
```

Git prints a link to open the pull request. Otherwise, on GitHub, click **Compare & pull request**
in the yellow banner, or go to **Pull requests** → **New pull request**.

![The Compare and pull request banner on GitHub](img/pr-banner.png)

Set the **base** to `dev`, add a title and a sentence, and click **Create pull request**.

## 2. Wait for `wft-render`

The platform renders your pipeline the way the merge build will, from your project's real
settings, and reports a status check called **`wft-render`**:

- yellow while it runs ("Rendering WorkflowTemplate in Argo Workflows"), a couple of minutes;
- green: "WorkflowTemplate rendered: N steps, M form params";
- red: "WorkflowTemplate render FAILED"; **Details** opens the Argo run with the error.

![The wft-render check passed, green, with the Merge button below](img/wft-render-green.png)

It checks that the steps are wired, that every step reads settings that exist, and that every step
has a Dockerfile. Nothing is built or released yet. A second check, **`kaos-lib/support`**, reports
whether your kaos-lib version is still supported ([kaos-lib versions](kaos-lib-versions.md)). It
never blocks the render.

**Details** opens the run that checked your pipeline. Green means the check finished.

If it is red, fix the one thing the message names and push again. The same pull request updates
and the check runs again.

```bash
git add . && git commit -m "fix the thing the check named" && git push
```

## 3. Merge

When it is green, click **Merge pull request** → **Confirm merge**. If your team reviews changes
first, wait for their approval.

## 4. Let the platform build

The merge starts **`kaos-ml-ci`**. It builds the step images whose folders changed and releases
a new version of `<app>-pipeline`. It reports on the merge commit, in a few minutes. The console
shows it under **Pipelines** → your app → **CI builds**.

When it is green, your step or setting is on the form. You never built an image, picked a machine,
or typed a password.

**Next:** [Run your pipeline](run-it.md).
