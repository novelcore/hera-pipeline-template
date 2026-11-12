"""prepare: keep the files of the run's dataset that are large enough, as a new version of the dataset `clean`."""
import shutil

from kaos_lib import step


def main() -> None:
    ctx = step.start()
    least = ctx.params["prepare"]["min_bytes"]  # a setting: config/prepare.yaml, a field on the run form
    data, clean = step.input("dataset"), step.output("clean")
    files = [f for f in sorted(data.rglob("*")) if f.is_file() and not f.name.startswith(".")]
    kept = [f for f in files if f.stat().st_size >= least]
    for file in kept:
        target = clean / file.relative_to(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
    print(f"[prepare] kept {len(kept)} of {len(files)} files", flush=True)
    step.result(files=len(kept), dropped=len(files) - len(kept))


if __name__ == "__main__":
    main()
