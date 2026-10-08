# `kubecore-dataset` — the dataset tool

The command-line tool that ships in this app repo. It gets a YOLO-pose dataset
from your laptop into your project's data store, at the place the pipeline reads
it. No cluster access, no keys — just your browser.

> If your app has a `.kubecore/dataset-config.yaml` (copy the example file and fill
> in the values your contact gives you), the tool discovers your lakeFS URL and repo,
> so you never type them. Otherwise pass `--url` and `--repo` on the command line.

For the full, newcomer-friendly walkthrough see the **Use your own data** page in
the project guide.


> **In this template** the one command is `python3 scripts/upload-dataset.py <folder> [name]`.
> It uploads any folder of files; it does not check a dataset format. The `validate`
> subcommand below checks the YOLO-pose format only, so skip it unless your data is YOLO-pose.
> The walkthrough is the **Use your own data** page of the project guide.
---

## Install

```bash
python3 -m venv .venv                 # from the app repo root
. .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install ./dataset_tools
```

Python 3.9+. Only needs `requests` and `pyyaml`. The virtual environment matters:
on recent Ubuntu, Debian and Homebrew Python a bare `pip install` is refused with
`externally-managed-environment`.

### If `kubecore-dataset` is "not found" / "not recognized"

`pip install` sometimes puts the `kubecore-dataset` command in a directory that
isn't on your `PATH` (pip even prints a warning like *"The script kubecore-dataset
is installed in '…/.local/bin' which is not on PATH"*). Two fixes:

- **Easiest — run it as a module** (works regardless of PATH, same commands):

  ```bash
  python -m dataset_cli login
  python -m dataset_cli validate ./my_dataset
  python -m dataset_cli sync ./my_dataset --branch my-dataset
  ```

- **Or put the scripts dir on PATH** — Linux/macOS: `export PATH="$HOME/.local/bin:$PATH"`
  (add it to `~/.bashrc`/`~/.zshrc`); Windows: add the `Scripts` dir pip named in its
  warning to your PATH.

Everywhere below you can swap `kubecore-dataset <cmd>` for `python -m dataset_cli <cmd>`.

---

## The one command you'll use

```bash
./scripts/upload-dataset.py  datasets/my_dataset  my-first-dataset
```

Logs you in (browser), validates the dataset, uploads it as the dataset named
**`my-first-dataset`**, saves a version. When you run the pipeline, type that same
name as **`data-ref`**. Leave the name out and it is `main`.

> **One name = one dataset.** Uploading to a name that already has a dataset
> *replaces* it with your folder: files you don't have locally are removed. The tool
> lists them and asks before deleting anything. Use a new name to keep both.

---

## The three subcommands

### `login` — browser sign-in

```bash
kubecore-dataset login
```

Opens your browser to log in with single sign-on and remembers the session (cached
locally at `~/.config/kubecore-ml/`). No keys touch your machine. If the automatic
browser flow can't finish, add `--paste` for a one-time guided sign-in.

### `validate` — check before you upload

```bash
kubecore-dataset validate datasets/my_dataset
```

Runs locally. Checks the dataset is a valid Ultralytics-pose set — `data.yaml` with
`path/train/val/kpt_shape/names`, the `train` and `val` splits present, every image
paired with a same-named label, and label rows in the right pose format. If anything
is off it prints exactly what, and stops — so a bad dataset never reaches a run.

### `sync` — upload what changed

```bash
kubecore-dataset sync datasets/my_dataset --branch my-first-dataset
```

Compares your folder to the stored version, uploads new/changed files, removes files
you deleted, and saves one new version. If anything would be removed it lists the
files and asks first (`--yes` skips the question). Re-running unchanged is a no-op.

---

## What a valid dataset looks like

```
my_dataset/
├── data.yaml
├── images/train/  *.jpg      # + images/val/
└── labels/train/  *.txt      # one .txt per image, same name; + labels/val/
```

```yaml
# data.yaml
path: .
train: images/train
val: images/val
kpt_shape: [11, 3]
names:
  0: spacecraft
```

---

## After uploading

Run your pipeline from the Argo UI and type your dataset name in the `data-ref`
field (it is usable immediately). See the **Run the pipeline** page in the project
guide.

---

## Options (rarely needed)

Everything is discovered from `.kubecore/dataset-config.yaml`. You only pass these if
you're running outside the app clone:

| Flag / env | What it is |
|---|---|
| `--url` / `LAKEFS_URL` | your lakeFS URL (auto-discovered otherwise) |
| `--repo` / `LAKEFS_REPO` | your lakeFS repo (auto-discovered otherwise) |
| `--branch` (sync) / 2nd argument (upload-dataset.py) | the dataset name, which is what you type as `data-ref` |
| `--data-version` | a version folder inside the dataset (default: same as the name) |
| `--yes` | don't ask before removing files that aren't in your folder |
| `--paste` | guided sign-in instead of the automatic browser flow |
| `--dry-run` | show what would change without uploading |

`kubecore-dataset --help` for everything.
