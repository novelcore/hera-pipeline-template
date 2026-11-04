# kaos-lib versions and upgrades

**kaos-lib** (import it as `kaos_lib`) is the Python package your steps use to read datasets, save run outputs and talk to MLflow. Its command-line tool is `kaosctl`. It used to be called `kubecore`; if you see `import kubecore` in older code, change it to `kaos_lib`.

## Which version does my pipeline use?

The platform chooses. When your step images are built, it replaces the value of this line in each step's Dockerfile with the version it recommends:

```dockerfile
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel]==0.4.0rc10"
RUN pip install --no-cache-dir --extra-index-url https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/simple/ PyYAML "${KAOS_LIB_PACKAGE}"
```

Keep the name `KAOS_LIB_PACKAGE`. The value in the file only applies to a build on your own laptop.

To see the version a run used, read the first lines of a step's log, or the `kaos_lib.version` tag on its MLflow run if your step sets it.

## Your own laptop

```bash
kaosctl --version     # your version, its channel, what the platform recommends
kaosctl upgrade       # install the recommended version (--dry-run shows it first)
```

Current prerelease: `0.4.0rc10`. Stable versions come only after a prerelease has passed testing; the [install page](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/install.html) always shows the newest of each. Install commands are in [Install kaosctl](cookbook/03-install-kaosctl.md).

## Holding a version

If you need to stay on one version, ask your project administrator to pin your pipeline to it. A pinned pipeline never moves when the platform's recommendation changes.

## Too old to work

When your version falls out of the support window, reads still work with a warning, but `create`, `release` and `push` are refused. Run `kaosctl upgrade`.
