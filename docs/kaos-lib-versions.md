# Package versions and upgrades

Your step images install **kaos-lib**, the platform's Python package for datasets and run
outputs (until its first release it is still installed under its former name, `kubecore`,
and your code keeps importing `kubecore`). This page explains who picks its version, how a
new version reaches your app, how to hold a version, and what a bump pull request is.

## Who picks the version

**The platform does.** Every time it builds your step images, the platform's CI passes the
version it chose to each step Dockerfile:

```dockerfile
ARG KAOS_LIB_PACKAGE="@ https://github.com/novelcore/hera-pipeline-template/archive/<commit>.zip#subdirectory=packages/kubecore"
RUN pip install --no-cache-dir "kubecore[zitadel] ${KAOS_LIB_PACKAGE}"
```

The value in the `ARG` line is only the default for a build on your own computer. In the
platform's build it is replaced, so changing it does not change what your pipeline runs.
Keep the name `KAOS_LIB_PACKAGE` in every step that installs the package: a step without
it keeps its default forever.

The version is a pip requirement: `==0.2.3` (a released version) or
`@ https://github.com/…/archive/<commit>.zip…` (a commit of the package, used until the
package is published).

## Your range: `.kaos/compat.yaml`

```yaml
kaos-lib: ">=0.2,<0.3"
```

This file says which released versions your code works with. The platform only moves your
app to a released version inside this range. You can edit it like any other file in your
app. While the package is installed from a commit (the `@ https://…` form), every commit
counts as inside your range; so does every version when the file is missing.

## How a new version arrives

- **Inside your range** (for example 0.2.3 → 0.2.4): the platform rebuilds your step images
  with the new version and updates your pipeline. Nothing is committed to your repository
  and you do nothing.
- **Outside your range** (for example 0.2.4 → 0.3.0): your images stay on the version they
  have, and the platform asks for a **bump pull request** (below). Until you merge it,
  every build of your app keeps the version it already runs.

## The bump pull request

- Its branch is `kaos-lib/bump-<version>`, for example `kaos-lib/bump-0.3.0`.
- It changes `.kaos/compat.yaml` to the new range (and any code change the release
  needs, if it names one).
- Its description has the release notes of that version: what changed and what you may need
  to change in your steps.

**Merge it** when you are ready: the push builds your images with the new version, the same
way any push does. Check your next run.

**Close it** if you are not ready: the platform does not open a second pull request for the
same version, and your app keeps the version it runs now. When a newer version comes out,
you get a new pull request for that one, and the platform closes the older one.

## Holding a version

- **From your repository**: narrow the range. `kaos-lib: "==0.2.4"` keeps exactly 0.2.4;
  a newer released version arrives as a bump pull request instead of a rebuild.
- **On the platform**: your Novelcore contact can pin your app to one version (the app's
  `kaosLib` setting). A pinned app is never moved when the platform's default changes, and
  gets no bump pull requests.

## Which version is my pipeline running?

- The first line of every step's log: `kaos-lib 0.2.0`.
- A step that logs an MLflow run should tag it `kaos_lib.version` (the yolo template's
  training and registration steps do).
- Each step image carries the label `io.kaos.lib` with the exact requirement it was built
  with.

## On your computer

To work with the same package your steps use, install it in a virtual environment with the
requirement from the step Dockerfile (or the one from the image label):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install "kubecore[zitadel] @ https://github.com/novelcore/hera-pipeline-template/archive/<commit>.zip#subdirectory=packages/kubecore"
```
