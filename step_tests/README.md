# step_tests/ - tests of the app's own code (uses kaos-lib)

The steps import **kaos-lib** (`kaos_lib`: datasets, run outputs), the platform library from
[kaos-io/kaos-lib](https://github.com/kaos-io/kaos-lib). Install the version the step images pin
(`KAOS_LIB_PACKAGE` in `steps/*/Dockerfile`), then run:

```bash
pip install "$(sed -n 's/^ARG KAOS_LIB_PACKAGE="\(.*\)"$/\1/p' steps/*/Dockerfile | head -1)" pytest
python -m pytest
```

`fake_lakefs.py` is kaos-lib's in-memory lakeFS (`tests/fake_lakefs.py` there), vendored at the same pin.

`test_repo_layout.py` fails if a copy of the pipeline engine or a step that composes the parameters comes
back: the platform runs its own pipeline engine, so an app holds only `pipeline.py`, `config/` and `steps/`.
