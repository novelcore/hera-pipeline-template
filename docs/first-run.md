# Guide: your first dataset and run

**Goal:** from nothing to a finished run on your own data, and its result on your computer. It uses
the pipeline this template ships with (the one step, `hello-world`), so you can do it
before you write any code.

**You need:** your app cloned and `kaosctl` signed in ([chapters 2 to 4](cookbook/2-your-apps.md)).
Your role is `dev`, `ops` or `admin`.

## 1. Run once on the empty `dataset-default`

Console → **Pipelines** → your app → **Run** → **Submit**, with every field left as it is.

**You should see** the step go green. The `hello-world` log says
`dataset-default@latest @ <commit> holds no files yet`. An empty dataset is not an error.

## 2. Create a dataset and put files in

```bash
kaosctl dataset create notes --layout none
mkdir -p notes && cp ~/some-files/* notes/
kaosctl dataset push ./notes dataset-notes -m "first files"
```

`push` opens a pull request and prints its link. For images and labels, follow
[Prepare and upload a yolo dataset](https://github.com/novelcore/yolo-pipelines-template/blob/dev/docs/prepare-dataset.md), in the yolo guide, instead.

## 3. Merge and release

Open the link, check the change in lakeFS, and **Merge**. Then click **Release version** on the
dataset in lakeFS, or:

```bash
kaosctl dataset release dataset-notes        # prints v1
```

## 4. Run on `v1`

Submit again. In the **`dataset`** dropdown pick `dataset-notes@v1`. If it is not there yet, wait a
few minutes and reopen the form.

**You should see** the `hello-world` log name `dataset-notes@v1`, its commit, and the folder it
read. The platform pinned that commit when the run started, so a merge during the run changes nothing.

## 5. Get the result

```bash
kaosctl dataset pull outputs-<app>@main ./results --prefix checkpoints/my-experiment-v1/<run>/
cat ./results/hello.json
```

`<run>` is the run's name, shown on the run page. `hello.json` names the dataset, the commit it read, and the
number of files.

## If it isn't there

See [When things go wrong](cookbook/10-when-things-go-wrong.md): the *Data* and *The run* sections.

**Next:** [Add a step that reads the dataset and writes a result](guide-step-with-data.md).
