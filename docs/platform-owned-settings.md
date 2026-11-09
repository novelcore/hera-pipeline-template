# Settings the platform owns

**Goal:** know what you must not set in `pipeline.py`, and what to do instead.

The platform decides which account every step runs as, and it sizes and places every step's pod. So when
you open a pull request, the `wft-render` check (and `./run.sh` on your computer) **fails** if `pipeline.py` or a
step sets any of these:

| you set | the message says | do this instead |
|---|---|---|
| `serviceAccountName` on the pipeline | "pipeline.py sets a service account for the whole pipeline" | remove it |
| `serviceAccountName` (or `executor.serviceAccountName`) on a step | "step '<name>' sets a service account" | remove it |
| `podSpecPatch` on the pipeline or a step | "sets podSpecPatch ... The platform sizes and places pods itself" | use `step(..., gpu=True, disk="30Gi")`; per run, the `<step>-class`, `<step>-cpu`, `<step>-mem` fields on the form |
| a step named `hpc-follower` (or `meluxina-run`) | "uses a name the platform reserves for its HPC follower" | rename the step |

Nothing is released while the check is red. The message names the step, so the fix is one edit. You do not need
any of these settings: placement on an HPC class is a choice on the run form, not something in `pipeline.py`
([Run on HPC (Slurm)](hpc.md)).
