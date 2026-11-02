# step_tests/ - tests of the step code (uses kaos-lib)

The steps import **kaos-lib** (`kaos_lib`: datasets, run outputs), the platform library from
[kaos-io/kaos-lib](https://github.com/kaos-io/kaos-lib). Install the version the step images pin
(`KAOS_LIB_PACKAGE` in `steps/*/Dockerfile`), then run:

```bash
python -m pytest tests                                       # engine (vendored kubecore/)
pip install "kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/<commit>.zip" pytest
pytest step_tests                                            # step code
```

`fake_lakefs.py` is kaos-lib's in-memory lakeFS (`tests/fake_lakefs.py` there), vendored at the same pin.
Keep the two runs apart: kaos-lib still ships a deprecated `kubecore` import shim for one release, and
the engine tests must import the vendored `kubecore/` engine, not that shim.
