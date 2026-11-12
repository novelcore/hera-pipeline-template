# Guide: your first dataset and run

**Goal:** from nothing to a finished run on your own data, and its result on your computer. It uses
the pipeline this template ships with (the two steps `prepare` and `hello-world`), so you can do it
before you write any code.

**You need:** your app cloned and `kaosctl` signed in ([chapters 2 to 4](cookbook/2-your-apps.md)).
Your role is `dev`, `ops` or `admin`.

## 1. Create a dataset and put files in

```bash
kaosctl dataset create notes --layout none
mkdir -p notes && cp ~/some-files/* notes/
kaosctl dataset push ./notes dataset-notes -m "first files"
```

`push` opens a pull request and prints its link. For images and labels, follow
[Prepare and upload a yolo dataset](https://github.com/novelcore/yolo-pipelines-template/blob/dev/docs/prepare-dataset.md), in the yolo guide, instead.

## 2. Merge and release

Open the link, check the change in lakeFS, and **Merge**. Then click **Release version** on the
dataset in lakeFS, or:

```bash
kaosctl dataset release dataset-notes        # prints v1
```

## 3. Run on `v1`

Console → **Pipelines** → your app → **Run**. In the **`dataset`** field pick `dataset-notes@v1`. If it
is not there yet, wait a few minutes and reopen the form. Press **Submit**.

**You should see** both steps go green. The `prepare` log says `kept N of N files`; the `hello-world` log
says `N files in clean, 0 dropped by prepare`. The platform fixed the dataset to one exact version when the
run started, so a merge during the run changes nothing.

The form's default is `dataset-default`, which holds no files until you push some. A run on an empty dataset
stops in `prepare` with `holds no files`.

## 4. Get the result

```bash
kaosctl dataset pull outputs-<app>@main ./results --prefix report/my-experiment-v1/<run>/
cat ./results/hello.txt
```

`<run>` is the run's name, shown on the run page. `hello.txt` names the experiment and the number of files.

The run also wrote a version of the dataset `dataset-clean`: the files `prepare` kept
([Results](results.md#the-dataset-the-pipeline-produces)).

## If it isn't there

See [When things go wrong](cookbook/10-when-things-go-wrong.md): the *Data* and *The run* sections.

**Next:** [Add a step that reads a dataset and writes a result](guide-step-with-data.md).
