# kubecore/ - helper code that ships with the template

This folder is part of the template and is replaced by the platform on upgrade: edits here are
lost. It turns your `pipeline.py` and `config/` tree into the run form and, at run time, into the one
resolved `params.yaml` every step receives. You never need to change it.

To change what your pipeline does, edit `pipeline.py`, `config/` and `steps/`. See the
[Pipeline Developer Guide](../DEVELOPER.md) and the [guide](../docs/index.md).

Local rendering (`./run.sh`) uses the placeholder values in `local-dev/`.
