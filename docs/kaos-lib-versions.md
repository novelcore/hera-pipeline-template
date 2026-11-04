# kaos-lib versions and upgrades

Your step images install **kaos-lib**, the KAOS Python package for datasets and run outputs
(`import kaos_lib`). The same package gives
you `kaosctl` on your computer. This page explains who picks its version, how a new version reaches
your app, how to hold a version, and how long a version is supported. The library itself is
documented in the [kaos-lib reference](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html).

!!! note "The minimum version"
    The `kaosctl` command exists from **0.4.0rc5** on. Releases are on the platform's package
    index, in two channels: *prerelease* (`kaos-lib-rc`, the `rc` versions) and *stable*
    (`kaos-lib`, which has no release yet). [Install kaosctl](cookbook/4-install-kaosctl.md) has the
    command for each.

## Who picks the version

**The platform does.** Every time it builds your step images, the platform's CI passes the
version it chose to each step Dockerfile:

```dockerfile
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/<commit>.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
```

The value in the `ARG` line is only the default for a build on your own computer. In the
platform's build it is replaced, so changing it does not change what your pipeline runs.
Keep the name `KAOS_LIB_PACKAGE` in every step that installs the package: a step without
it keeps its default forever.

The value is a whole pip requirement: the package's name and extras, then the version.
In the platform's build it is the requirement of the newest kaos-lib release on the platform's channel,
for example `kaos-lib[zitadel] @ https://<registry>/kaos_lib-X.Y.Z-py3-none-any.whl#sha256=<hex>`, with
no change in your repository.

## Your range: `.kaos/compat.yaml`

```yaml
kaos-lib: ">=0.4.0rc1,<0.5"
```

This file says which released versions your code works with. The platform only moves your
app to a released version inside this range. You can edit it like any other file in your
app. While the package is installed from a commit (the `@ https://…` form), every commit
counts as inside your range; so does every version when the file is missing.

## How a new version arrives

- **Inside your range** (for example 0.4.1 → 0.4.2): the platform rebuilds your step images
  with the new version and updates your pipeline. Nothing is committed to your repository
  and you do nothing.
- **Outside your range** (for example 0.4.2 → 0.5.0): your images stay on the version they
  have, and the platform asks for a **bump pull request** (below). Until you merge it,
  every build of your app keeps the version it already runs.

## The bump pull request

- Its branch is `kaos-lib/bump-<version>`, for example `kaos-lib/bump-0.5.0`.
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

- **From your repository**: narrow the range. `kaos-lib: "==0.4.2"` keeps exactly 0.4.2;
  a newer released version arrives as a bump pull request instead of a rebuild.
- **On the platform**: your KAOS contact can pin your app to one version (the app's
  `kaosLib` setting). A pinned app is never moved when the platform's default changes, and
  gets no bump pull requests.

## Which version is my pipeline running?

- The first line of every step's log: `kaos-lib 0.4.0rc5`.
- A step that logs an MLflow run should tag it `kaos_lib.version` (the yolo template's
  training and registration steps do).
- Each step image carries the label `io.kaos.lib` with the exact requirement it was built
  with.

## How long a version is supported

Every release carries the platform's support policy: which versions are still supported, and which
are deprecated and until when. The newest release's policy applies. kaos-lib gives each version
one of these verdicts:

| verdict | what it means | what happens |
|---|---|---|
| `current` | the newest release | nothing |
| `behind` | older, still supported | a warning |
| `deprecated` | outside the supported range, before its deadline | a warning that names the deadline |
| `unsupported` | outside the supported range, past its deadline | `kaosctl` refuses the commands that change data (`create`, `push`, `release`, `publish`) |

Where you see it:

- **`kaosctl`** prints a `WARNING:` line with the fix, and `kaosctl --version` shows the
  recommended version; `kaosctl upgrade` moves you to it.
- **Pull requests and builds** get a `kaos-lib/support` check. It is green when current, green with
  "warning:" when behind or deprecated, and red when unsupported. It never fails the render or the
  build itself.

The policy for each release is in the [kaos-lib reference](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html).

## On your computer

To work with the package your steps use, install it as in
[Install kaosctl](cookbook/4-install-kaosctl.md), with the version from the step image's
`io.kaos.lib` label or from the first line of a step log.
