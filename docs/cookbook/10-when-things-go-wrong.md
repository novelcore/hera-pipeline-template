# 10. When things go wrong

Messages are quoted as `kaosctl` prints them. More on pipeline checks: [When something breaks](../troubleshooting.md).

| You see | What it means | Do this |
|---|---|---|
| `ERROR: not signed in. Run kaosctl login, ...` | No session, or it expired. | `kaosctl login` |
| `ERROR: --classes and --param fill a layout's parameters, and no layout is named ...` | A new dataset has no layout unless you name one. | Add `--layout yolo` (or another from `kaosctl layout list`). |
| `<folder> has N problem(s) for layout yolo:` and a list | Your folder does not match the layout. | Fix each listed line, run `kaosctl dataset validate <folder>` again, then push. |
| `ERROR: cannot release team-a/...: ... read-only. Ask team-a to release it.` | You are using another project's shared dataset. | Ask that project. |
| `kaosctl: command not found` | The virtual environment is not active. | `. .venv/bin/activate` |
| `externally-managed-environment` when installing | Your system Python refuses installs. | Install inside a virtual environment, as in [step 3](03-install-kaosctl.md). |
| `No matching distribution found for PyJWT` (or another dependency) | You gave pip only the `kaos-lib` index. | Add `--extra-index-url https://pypi.org/simple/`. |
| `cannot determine the lakeFS URL` | `kaosctl` was not run in your pipeline folder. | `cd` into your pipeline's code folder, or pass `--url`. |
| A version is missing from the run form's dataset dropdown | The release has not shown up yet, or it was never released. | Wait a minute and reload the form. Check `kaosctl dataset versions dataset-<name>`; if it is not listed, release it ([step 4](04-create-a-dataset.md)). |
| A step box is red | The step stopped with an error. | Click it and read the last lines of its log. |
| The run stops at once with a list of allowed values | A field accepts a fixed set of choices. | Pick one of the listed values. |
| `kaosctl` refuses `create`, `release` or `push` as unsupported | Your `kaos-lib` is too old. | `kaosctl upgrade` |

Still stuck? Send your project administrator the exact message and what you were doing.
