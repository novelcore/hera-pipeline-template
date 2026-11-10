# 10. When things go wrong

**Goal:** find your symptom and fix it. The sections follow the order of the day.

**The habit that solves most of them:** read the message. A red check has a **Details** link, and
a red step has a log. Read the last lines first. KAOS errors name the one thing to fix, and
`kaosctl` prints a single `ERROR:` line.

## Signing in and access

| symptom | cause and fix |
|---|---|
| the console shows no project | you are not on a team with access to it. An organisation admin adds you ([chapter 1](1-youre-in.md)) |
| added to a team, still no access | the team links your sign-in e-mail; check it is the exact address. Wait a few minutes, then sign out and in again |
| `403` in Argo, lakeFS or MLflow | your role does not cover that project or that action ([chapter 1](1-youre-in.md)) |
| no **Identity & Access** in the sidebar | only organisation admins see it |

## The app and its first build

| symptom | cause and fix |
|---|---|
| no **New pipeline**, or the project is not offered | the project cannot host an ML pipeline yet; ask a project admin |
| stuck on **Awaiting first build** | the build was not triggered; check the repository and its `dev` branch exist, then ask your KAOS contact |
| **Build failed** | **View run** opens the build in Argo; read the failing step |

## kaosctl

| symptom | cause and fix |
|---|---|
| `kaosctl: command not found` | activate the virtual environment, or install kaos-lib 0.4.0rc5 or newer ([chapter 4](4-install-kaosctl.md)) |
| `cannot determine the lakeFS URL` | run it inside your app folder |
| `externally-managed-environment` from `pip` | install inside a virtual environment ([chapter 4](4-install-kaosctl.md)) |
| the browser does not open on `kaosctl login` | open the printed link yourself; the tool waits about three minutes |
| `pip` cannot find `kaos-lib` | use the platform's index (`--index-url ...`) and keep `--extra-index-url https://pypi.org/simple/` for its dependencies |

## Data

| symptom | cause and fix |
|---|---|
| `push` stops and lists problems (exit code 2) | fix each one; for yolo, every label needs its image, and every class id must be below the number of `names` ([Check a dataset](../dataset-validate.md)) |
| `push` opened a pull request but `main` is unchanged | merge the pull request in lakeFS |
| the new version is not in the run form's dropdown | the list is refreshed after a release; wait a few minutes and reopen the form |
| a shared dataset is not in the dropdown | the owner has not saved the sharing, or your pipeline has not been refreshed since |
| `push` to a shared dataset is refused | only the owning project writes it |

## The pull request checks

| symptom | cause and fix |
|---|---|
| `wft-render` red: a step has no Dockerfile | add `steps/<step_name>/Dockerfile`; folder names use underscores, step names use dashes |
| `wft-render` red: a step reads a section that does not exist | fix `reads=` in `pipeline.py` and `READS` in the step, or add the section to `config/` |
| `wft-render` red: a step needs a step that is gone | remove it from the `needs=` list ([Remove a step](../remove-a-step.md)) |
| no `wft-render` at all | the pull request is not into `dev` |
| `kubecore-ml-ci` red after the merge | open its **Details**; it is the build of a step image or of the pipeline |
| my step did not rebuild | only steps whose folder changed are rebuilt; your change is still live |
| my new setting is not on the form | only plain values become fields; a long list or a nested block does not ([Change a setting](../change-a-setting.md)) |

## The run

| symptom | cause and fix |
|---|---|
| it stops in seconds with "invalid value" | a field is outside its allowed values; the message lists them |
| `hello-world` fails reading the dataset | the dataset or version does not exist; the message lists what does |
| `hello-world` says "holds no files yet" | the dataset is empty; this is not an error. Push data and release a version ([chapter 5](5-your-data.md)) |
| a step stays **Pending** | no machine of that class is free yet; give it a few minutes. On an HPC class (`meluxina-*`) it waits in the HPC queue; its log gives the reason ([why a step is waiting or refused](../hpc.md#why-a-step-is-waiting-or-refused)) |
| a step is red with `ImagePullBackOff` | its image was not built; check `kubecore-ml-ci` for that commit |
| a step is red with `OOMKilled` | it ran out of memory; pick a bigger `<step>-class` or raise `<step>-mem` |
| a retry started from scratch | you used **Resubmit**, which is a new run; **Retry** keeps the run name and resumes ([chapter 7](7-run-it.md)) |

## Results and MLflow

| symptom | cause and fix |
|---|---|
| nothing in `outputs-<app>` | the step failed before `finish()`; its saves wait on `run-<run>-<kind>` for a retry |
| no MLflow run | the step does not log to MLflow ([Results](../results.md#log-to-mlflow-from-a-step)) |
| MLflow `401` from your laptop | `kaosctl login` again, inside the app folder |
| `kaosctl run --lock`: the run has no data lock | the step never called `kaos_lib.lock.write` |

## HPC (Slurm)

| symptom | cause and fix |
|---|---|
| no `meluxina-*` in the class dropdown | your project has no HPC (Slurm) environment yet ([Run on HPC (Slurm)](../hpc.md)) |
| an HPC step waits for hours | the Slurm queue is busy; the waiting time is real |
| it ends at its time limit | raise `hpc_time_limit` for the step in `pipeline.py`, or write its checkpoints into `KAOS_CHECKPOINT_DIR` so it continues ([details](../resilience.md)) |
| it is refused with `TooLongNotResumable` | its time limit is longer than one HPC job may run and the step is not resumable: make it resumable or shorten it ([details](../hpc.md#long-runs-continue-after-the-time-limit)) |
| it fails with `SubmitLimit` | the site allows only so many queued and running jobs; run it again when some have finished |
| it waits with `SiteLimit` or `BudgetBlocked` | the allocation for that kind of machine (GPU, CPU, ...) is used up; ask your KAOS contact ([details](../hpc.md#why-a-step-is-waiting-or-refused)) |
| a step ran twice after a machine was reclaimed | by design: it is repeated at most twice, from its last checkpoint if it wrote one ([details](../resilience.md)) |
| the render fails: "sets a service account", "sets podSpecPatch" or "reserves" a name | `pipeline.py` set something the platform owns ([Settings the platform owns](../platform-owned-settings.md)) |
| it ends with `Idle` | no GPU use and no new log lines for 20 minutes; raise `idle_timeout` if it was working |

## Still stuck

Copy the exact message and the run name, say what you were doing, and send it to your KAOS
contact.
