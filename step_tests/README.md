# step_tests/ - tests of the step code (uses kaos-lib)

The steps import **kaos-lib** (`kaos_lib`: datasets, run outputs), the platform library from
[kaos-io/kaos-lib](https://github.com/kaos-io/kaos-lib). Install the version the step images pin
(`KAOS_LIB_PACKAGE` in `steps/*/Dockerfile`), then run:

```bash
python -m pytest tests                                       # engine (vendored kaos_pipeline/)
pip install "$(sed -n 's/^ARG KAOS_LIB_PACKAGE="\(.*\)"$/\1/p' steps/*/Dockerfile | head -1)" pytest
pytest step_tests                                            # step code
```

`fake_lakefs.py` is kaos-lib's in-memory lakeFS (`tests/fake_lakefs.py` there), vendored at the same pin.
Keep the two runs apart: the engine tests import the vendored `kaos_pipeline/` engine, the step tests import `kaos_lib`.
