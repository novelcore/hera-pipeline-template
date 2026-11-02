"""kubecore: the KAOS platform package (datasets, run outputs, CLI).

Public API:
    kubecore.datasets  DatasetRef, resolve, list_datasets, versions, release, create_dataset, materialize
    kubecore.outputs   outputs_repo, write_run
    kubecore.formats   get_format (creator + consumer pairs, first: ultralytics)
    kubecore.peers     the projects whose shared datasets this one reads (peers, shared)
"""
__version__ = "0.2.0"
