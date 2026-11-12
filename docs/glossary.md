# Word list

Plain meanings for the words in this guide. One sentence each. Come back here any time.

**Branch.** A safe copy of the project where you make changes before they are accepted.

**Clone.** To copy the project from GitHub onto your computer, one time.

**Commit.** A saved change with a short note describing it.

**Config.** Your settings. They live in the `config/` folder, and each one becomes a field on the run page.

**Data lock.** The record of every dataset version a step read, kept on its MLflow run. `kaosctl run --lock` replays it.

**Dataset.** A lakeFS repository called `dataset-<name>`. Its versions are tags (`v1`, `v2`, ...); a run picks one in the `dataset` field. Changes reach its `main` through pull requests.

**Dockerfile.** A small recipe that says how to pack a step into a box the platform can run.

**Dropdown.** A field that lets a person pick from a fixed set of choices instead of typing.

**Field.** A single box on the run page that a person can fill in or change.

**Git.** The tool that copies the project to your computer and sends your changes back.

**GitHub.** The website where the project lives, with a full history of every change.

**Hera.** The Python library behind `pipeline.py`. It lets you describe steps and their order in a few plain lines. Also the name of this template.

**Image.** The small self contained box a step becomes after it is built. It holds the code and everything it needs to run.

**KAOS console.** The web app of your organisation: projects, apps, pipelines, datasets, models, and Identity & Access.

**kaosctl.** The command-line tool that comes with kaos-lib: create, push, validate, release and pull datasets, and replay a run's data ([Install it](cookbook/4-install-kaosctl.md)).

**kaos-lib.** The platform's Python package (`import kaos_lib`) for datasets, results and MLflow, with the `kaosctl` command. This template needs 0.5 or newer. Reference: [the kaos-lib reference](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html).

**kubecore-ml-ci.** The name of the build that runs after a merge into `dev`: it builds the changed step images and releases a new version of the pipeline.

**lakeFS.** Your project's data store. It keeps every version of every file, like Git does for code. Datasets and `outputs-<app>` live there.

**Layout.** The shape a dataset must have, such as `yolo` (images, labels, `data.yaml`). `validate` and `push` check it. `none` means any files.

**HPC (Slurm).** A supercomputer that schedules jobs with Slurm. On a project with an HPC (Slurm) environment a step can run there by picking an HPC class ([Run on HPC (Slurm)](hpc.md)).

**Merge.** To accept a pull request, which makes the change part of the project for real.

**MLflow.** Your project's tracking server: the metrics, parameters and artifacts of runs, and the registered models.

**Needs.** The setting in `pipeline.py` that says which step must finish before another can start.

**Pipeline.** Your list of steps that run in order.

**Platform.** The system that builds your steps, runs them, and handles all the servers so you do not have to.

**Pull request.** A proposal on GitHub to add your changes to the project. It gets checked before it is accepted.

**Push.** To send your saved changes from your computer up to GitHub.

**Reads.** `reads=` in `pipeline.py`: the sections of `config/` a step gets.

**Release.** Tagging the head of a dataset's `main` as the next version, with **Release version** or `kaosctl dataset release`.

**Render.** A preview of your pipeline that the platform builds to check your work. It does not run anything.

**Results.** What your steps write: one commit per step per run in your app's `outputs-<app>` repository.

**Role.** What a team gives its members on a project: `admin`, `ops`, `dev` or `business` ([You're in](cookbook/1-youre-in.md)).

**Run page.** The web page of your pipeline's runs. It has the form with the Submit button and shows each step as it runs. The console's **Pipelines** page links to it.

**Step.** One job in your pipeline, like preparing data or training a model.

**Submit.** The button on the run page that starts a run.

**Terminal.** The app where you type commands, like the ones in this guide.

**wft-render.** The name of the check that runs on your pull request into `dev` to confirm your pipeline is valid.
