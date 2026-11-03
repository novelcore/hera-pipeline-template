# Guide: upload images and labels for yolo

**Goal:** a yolo dataset with your labelled images, checked, merged and released as `v1`.

**You need:** `kaosctl` signed in, inside your app folder ([chapter 4](cookbook/4-install-kaosctl.md)),
and your images with one YOLO label file each.

## 1. Create the dataset with your classes

List the classes in label-id order. The first one is id `0`.

```bash
kaosctl dataset create cats --classes cat,kitten --description "street cats, 2026"
```

In the browser: lakeFS → **Datasets** → **New dataset** → layout **yolo**, one class per line.

## 2. Get the starter layout

```bash
kaosctl dataset pull dataset-cats@latest ./dataset-cats
```

```
dataset-cats/
├── data.yaml            path, train, val, test, names
├── images/{train,val,test}/
└── labels/{train,val,test}/
```

`train` and `val` are required. `test` is optional.

## 3. Put in your images and labels

Each image `images/<split>/<name>.<ext>` needs a label file `labels/<split>/<name>.txt`, with one
line per object:

```
# detection:     class x_center y_center width height        (all in 0..1)
0 0.481 0.512 0.230 0.310
# pose: the same, then x y visibility for each keypoint (kpt_shape in data.yaml)
0 0.481 0.512 0.230 0.310 0.47 0.40 2 0.52 0.41 2
```

Segmentation labels (`class x1 y1 x2 y2 …`) are accepted too. Images can be `.jpg`, `.jpeg`,
`.png`, `.bmp`, `.tif`, `.tiff` or `.webp`.

```bash
cp ~/export/images/train/* ./dataset-cats/images/train/
cp ~/export/labels/train/* ./dataset-cats/labels/train/
cp ~/export/images/val/*   ./dataset-cats/images/val/
cp ~/export/labels/val/*   ./dataset-cats/labels/val/
```

## 4. Validate

```bash
kaosctl dataset validate ./dataset-cats
```

**You should see** `./dataset-cats is a valid yolo dataset ...` and exit code 0. Otherwise every
problem is listed (exit code 2), for example
`class id 3 is outside 0..1`, `data.yaml: nc is 3 but names has 2 entries`, or
`images/val/ has no images`. Fix them and validate again.

## 5. Push, merge, release

```bash
kaosctl dataset push ./dataset-cats dataset-cats -m "first 200 labelled images"
```

Open the pull request link, check the change in lakeFS, and **Merge**. Then:

```bash
kaosctl dataset release dataset-cats      # v1
```

To change the classes later, open `data.yaml` in lakeFS and use **Edit** (Edit classes). It saves
through a pull request and keeps `nc` in step with `names`.

**Next:** train on it: [the yolo use case](cookbook/9-the-yolo-use-case.md), or read it from your own
step: [Add a step that reads the dataset](guide-step-with-data.md).
