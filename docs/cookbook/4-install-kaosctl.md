# 4. Install kaosctl and sign in

**Goal:** the `kaosctl` command on your computer, signed in to your project. You do this once per
computer.

**Who can do it:** anyone on a project team. You need your app cloned
([chapter 2](2-your-apps.md)) and Python 3.9 or newer (`python3 --version`).

## 1. Install it

`kaosctl` comes with **kaos-lib**, the KAOS Python package. Install it in a virtual
environment of its own:

=== "Development projects (prerelease)"

    ```bash
    python3 -m venv ~/.venvs/kaos
    . ~/.venvs/kaos/bin/activate          # Windows: %USERPROFILE%\.venvs\kaos\Scripts\activate
    pip install --index-url https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/simple/ \
        --extra-index-url https://pypi.org/simple/ "kaos-lib[zitadel,mlflow]>=0.4.0rc22"
    ```

=== "Production projects (stable)"

    ```bash
    python3 -m venv ~/.venvs/kaos
    . ~/.venvs/kaos/bin/activate          # Windows: %USERPROFILE%\.venvs\kaos\Scripts\activate
    pip install --index-url https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib/simple/ \
        --extra-index-url https://pypi.org/simple/ "kaos-lib[zitadel,mlflow]==<version your KAOS contact gives you>"
    ```

    The stable channel has no release yet. Until it has one, use the prerelease line.

The first address is the KAOS package index; kaos-lib is not on PyPI. The second brings
kaos-lib's own dependencies from PyPI. The `zitadel` extra is for datasets that other projects share
with yours. The `mlflow` extra is for MLflow and for `kaosctl run --lock`
([chapter 8](8-results-and-weights.md)).

!!! warning "Version 0.4.0rc5 or newer"
    The command is called `kaosctl` from kaos-lib **0.4.0rc5** on. Older versions only have
    `kaos-cli`, which still works as a hidden alias and prints a note. The `kubecore` command and
    package are the deprecated names from before kaos-lib. If you get `kaosctl: command not found`,
    run the `pip install` line above again with `-U`. `kaosctl lint`, `kaosctl dev`, `kaosctl step run` and
    `kaosctl build` need **0.4.0rc22** or newer ([Check and try a step on your computer](../check-and-try-locally.md)).

!!! tip "Why the virtual environment?"
    Many computers no longer let `pip install` change the system's own Python. You then see a
    message that mentions `externally-managed-environment`. The virtual environment avoids that.
    Run `. ~/.venvs/kaos/bin/activate` again in every new terminal.

## 2. Check the version

```bash
kaosctl --version
```

This prints the version, its channel (`prerelease` or `stable`) and the version KAOS
recommends. To move to the recommended one:

```bash
kaosctl upgrade
```

## 3. Sign in

```bash
kaosctl login
```

Your browser opens once and asks you to sign in. Sign in with your KAOS account, close the tab, and
go back to the terminal. The tool remembers you.

Run `kaosctl` **inside your app folder**. The folder has `.kubecore/dataset-config.yaml`, which tells
the tool where your project's lakeFS is, so you never type an address or a password. Sign in from
inside the app folder too: the session it makes then also opens your project's MLflow.

## What you should see

```bash
kaosctl dataset list
```

This lists the datasets of your project, starting with `dataset-default`.

## If it isn't there

| symptom | fix |
|---|---|
| `kaosctl: command not found` | the virtual environment is not active (`. ~/.venvs/kaos/bin/activate`), or the version is older than 0.4.0rc5 |
| `ERROR: cannot determine the lakeFS URL. Run inside your app clone ...` | you are not in your app folder; `cd` into the clone |
| the browser does not open | copy the link `kaosctl login` prints into your browser; the tool waits about three minutes |
| `403` from lakeFS | your account is not on a team of this project ([chapter 1](1-youre-in.md)) |

The full command list is in the [kaos-lib CLI reference](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/generated/cli.html).

**Next:** [5. Your data](5-your-data.md).
