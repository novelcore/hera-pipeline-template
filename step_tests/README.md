# step_tests/ - tests of your step code

Most tests call a step in this process with
`kaos_lib.testing.running` (guide page: try-it-locally);
one runs the steps one after the other with
`kaosctl step run` (guide page: try-it-locally), as the platform
runs them. No cluster, no login, nothing uploaded. Install `kaosctl` with pip from your platform's package index. Your platform admin, or the console of your platform, gives you the index and the version to install. That one install brings everything a step uses, the MLflow client included: there is nothing to add to it. To move to a newer version later, run `kaosctl upgrade`. Then run:

```bash
pip install pytest
python -m pytest
```

What the steps write through `kaosctl step run` stays in `.kaos/local/`, which is never committed.

| file | what it checks |
| --- | --- |
| `test_example_steps.py` | `prepare` writes the dataset `clean`; `hello-world` reads it; both again through `kaosctl step run` |
| `test_step_contract.py` | every step starts with `step.start()`, ends with `step.result(` and reads no variable and no argument |
| `test_kaos_lib_version.py` | every step image installs kaos-lib the way the platform expects, and the installed version is inside `.kaos/compat.yaml` |
| `test_gpu_example.py` | the example GPU step fails loudly without a GPU |
