"""hello-world: count the files `prepare` wrote in this run and save a small report."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    clean = step.input("clean")  # the version of the dataset `clean` that `prepare` wrote in this run
    files = sum(1 for f in clean.rglob("*") if f.is_file())
    dropped = step.upstream("prepare").values["dropped"]  # a value `prepare` handed on
    line = f"{ctx.experiment}: {files} files in clean, {dropped} dropped by prepare"
    (step.output("report") / "hello.txt").write_text(line + "\n")
    print(f"[hello-world] {line}", flush=True)
    step.result(files=files)


if __name__ == "__main__":
    main()
