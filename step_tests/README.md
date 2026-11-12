# step_tests/ - tests of your step code

Most tests call a step in this process with
[`kaos_lib.testing.running`](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/try-it-locally.html);
one runs the steps one after the other with
[`kaosctl step run`](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/try-it-locally.html#run-steps-the-way-the-platform-does), as the platform
runs them. No cluster, no login, nothing uploaded. Install kaos-lib at the version the step images install
(`KAOS_LIB_PACKAGE` in `steps/*/Dockerfile`), then run:

```bash
pip install "$(sed -n 's/^ARG KAOS_LIB_PACKAGE="\(.*\)"$/\1/p' steps/*/Dockerfile | head -1)" pytest
python -m pytest
```

What the steps write through `kaosctl step run` stays in `.kaos/local/`, which is never committed.

| file | what it checks |
| --- | --- |
| `test_example_steps.py` | `prepare` writes the dataset `clean`; `hello-world` reads it; both again through `kaosctl step run` |
| `test_step_contract.py` | every step is at most 25 lines and gets everything from `kaos_lib.step` |
| `test_kaos_lib_version.py` | every step image installs kaos-lib the way the platform expects |
| `test_repo_layout.py` | the app holds `pipeline.py`, `config/` and `steps/`, and no copy of platform code |
| `test_gpu_example.py` | the example GPU step fails loudly without a GPU |
| `test_docs_example.py` | the files the guide of kaos-lib shows equal this template (needs `DOCS_CHECK_KAOS_LIB`; skipped without it) |
