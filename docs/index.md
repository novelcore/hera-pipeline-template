# Start here

You were given a KAOS account and a project. This guide takes you from sign-in to a trained model, in plain steps.

**hera** is the starter ("scaffold") template for ML pipelines on KAOS. A pipeline is a list of steps, such as prepare data, then train, then report. You write them in Python, keep your settings in simple files, and push to your pipeline's code repository. KAOS builds the steps, puts your settings on a run form and runs the pipeline on the machines of your choice. For object detection there is a ready-made template, **yolo**, built on hera.

## The 5-minute path

1. Sign in to the KAOS console and look around: [You are in](cookbook/01-you-are-in.md).
2. Install `kaosctl` and sign in: [Install kaosctl](cookbook/03-install-kaosctl.md).
3. Create a dataset and release `v1`: [Create a dataset](cookbook/04-create-a-dataset.md).
4. In the console, **Machine learning → Pipelines → New pipeline**: [Create your pipeline](cookbook/05-create-your-pipeline.md).
5. Open its run page, pick `dataset-<name>@v1` and press **Submit**: [Run it](cookbook/07-run-it.md).

## The cookbook

| # | Page | You will |
|---|---|---|
| 1 | [You are in](cookbook/01-you-are-in.md) | Sign in and learn the console |
| 2 | [Your project](cookbook/02-your-project.md) | Understand where a pipeline can run |
| 3 | [Install kaosctl](cookbook/03-install-kaosctl.md) | Get the data tool on your laptop |
| 4 | [Create a dataset](cookbook/04-create-a-dataset.md) | Upload data and release a version |
| 5 | [Create your pipeline](cookbook/05-create-your-pipeline.md) | Start from hera or yolo |
| 6 | [Change a step](cookbook/06-change-a-step.md) | Read your dataset in code and push |
| 7 | [Run it](cookbook/07-run-it.md) | Pick a dataset version and submit |
| 8 | [See the results](cookbook/08-see-results.md) | Metrics, weights, comparing runs |
| 9 | [Share a dataset](cookbook/09-share-a-dataset.md) | Read another project's data |
| 10 | [When things go wrong](cookbook/10-when-things-go-wrong.md) | Real messages and fixes |

## Reference

[How it works](how-it-works.md) (optional) · [kaos-lib versions](kaos-lib-versions.md) · [Add a step](add-a-step.md) · [Remove a step](remove-a-step.md) · [Change a setting](change-a-setting.md) · [Troubleshooting](troubleshooting.md) · [Word list](glossary.md)

The library behind it all, kaos-lib, has its own docs: [kaos-lib documentation](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html).
