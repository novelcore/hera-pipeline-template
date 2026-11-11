# 9. The yolo use case

**Goal:** the whole day again, with a real training pipeline. You create a yolo app, label and
upload images, train on a released version, compare two trainings in MLflow, and pick the weights.

**Who can do it:** the same roles as chapters 2 to 8: `dev`, `ops` or `admin` on the project.

The yolo template is built on this one. It has the same `pipeline.py`, `config/` and `steps/`
shape, the same kaos-lib, the same datasets and the same outputs. Its pipeline has five steps:

```
config-validation → model-training → qat-finetune → model-quantization → model-registration
```

`qat-finetune` and `model-quantization` run only when you turn quantization on.

## The worked day

The yolo guide walks it through with every click and command:
**[A day with yolo](https://github.com/novelcore/yolo-pipelines-template/blob/dev/docs/worked-day.md)**. In short:

1. **Create the app**: console → **Pipelines** → **New pipeline** → the yolo card
   ([chapter 2](2-your-apps.md)).
2. **Label and upload**: one `.txt` label per image, then `kaosctl dataset push`, merge the pull
   request, and **Release version** ([Upload images and labels for yolo](../guide-upload-yolo.md)).
3. **Train twice on `v1`**: submit once with `train-epochs` = 50 and once with 100, or with two
   class sets released as `v1` and `v2`. Give each run a different `experiment-name` or keep one name
   and compare the runs inside it.
4. **Compare**: MLflow → the experiment → tick both runs → **Compare**; the experiment's **Models**
   tab lists each run's `<experiment-name>-best` with `val/mAP50_95`.
5. **Pick the weights**: download `best.pt` of the winner from `outputs-<app>`, or promote its
   registered version to `champion` ([chapter 8](8-results-and-weights.md)).

**Next:** [10. When things go wrong](10-when-things-go-wrong.md).
