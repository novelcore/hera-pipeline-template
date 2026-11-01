# step_tests/ - tests of the step code (use the kubecore package)

The steps import the kubecore PACKAGE (datasets, outputs). The repo root also holds the
vendored engine, also named `kubecore`, which `tests/` imports. The two must never share a
`sys.path`, so they run as two commands:

```bash
python -m pytest tests                                        # engine (vendored kubecore/ on the path)
pip install ./packages/kubecore pytest && pytest step_tests   # step code (the package on the path)
```

Use the `pytest` command, not `python -m pytest`, here: `python -m` puts the repo root on
`sys.path` and the vendored engine would shadow the package. `conftest.py` refuses to run if it does.
