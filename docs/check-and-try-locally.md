# Check and try a step on your computer

Before you open a pull request you can check the pipeline, set up each step, run one step and build its image on your own
computer. These commands come with `kaosctl` (kaos-lib **0.4.0rc22** or newer; [install it](cookbook/4-install-kaosctl.md)).
They run from your app folder, the one that holds `pipeline.py` and `steps/`.

| Command | What it does | Needs |
|---|---|---|
| `kaosctl lint` | reads `pipeline.py`, `config/` and your step folders and reports problems the platform would refuse, or that usually go wrong later (a step limit longer than the longest HPC (Slurm) run with no way to continue, an unpinned dataset, a Dockerfile problem). It never runs your code | nothing: no login, no network |
| `kaosctl render --context FILE` | renders `pipeline.py` with the pipeline engine the platform uses and writes `out/raw-workflow-template.yaml`: a render that passes here passes on your pull request. Your app holds no copy of the engine | the platform's pipeline-context file of your app (or `--engine-wheel`), and Python 3.11 or newer |
| `kaosctl dev` | gives each step its own Python environment from what its Dockerfile installs | Python and a package index connection |
| `kaosctl step run <step>` | starts one step the way the platform does, in its environment, with an optional small sample of your dataset | the step's environment |
| `kaosctl build [step]` | builds the step image with the same Dockerfile and arguments as the platform's build, and never pushes | a container engine on your computer; `kaosctl build` tells you which and how to get it |

## The same check on your pull request

The platform runs the same linter on every pull request and reports it as the **`pipeline-lint`** status, with one comment
that is updated on each push. Errors fail the status; warnings and infos do not. The report is the one `kaosctl lint` prints
for the same files. Run `kaosctl lint` first and you meet the problem before the pull request does.

```bash
kaosctl lint
```

Every finding names the file and line, says how to fix it and links to its page in the reference.

## A step that can continue on HPC (Slurm)

The linter decides whether a step can continue from a checkpoint from evidence, not from guessing: what `pipeline.py` says
(`resumable=`), what the platform saw when an earlier continuation of the step loaded its checkpoint and got further, or what
your step code does with the checkpoint folder. With no evidence, it stays silent. If you declared `resumable=` and a
continuation of the step was seen starting over, it warns with **L-W05**. See [Run on HPC (Slurm)](hpc.md).

## More

The full guides are in the kaos-lib reference: [Check your pipeline](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/lint.html), [Set up your steps](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/dev.html),
[Run a step locally](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/step-run.html), [Build a step image](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/build.html) and
[Troubleshooting dev, run, build](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/troubleshooting-build.html).
