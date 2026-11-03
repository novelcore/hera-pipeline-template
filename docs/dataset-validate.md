# Check a dataset

**Goal:** know a folder fits its layout before you push it, with every problem listed at once.

```bash
kaosctl dataset validate ./dataset-cats                 # the yolo layout by default
kaosctl dataset validate ./my-folder --layout none      # any files: nothing to check
```

For a **yolo** dataset it checks, among others:

- every image has a label file and every label file has an image;
- every class id is in `names`;
- each label line has the right number of values (detection `cls x y w h`, segmentation polygons,
  pose keypoints that match `kpt_shape`), with coordinates between 0 and 1.

## What you should see

`… is a valid yolo dataset.` and exit code `0`. Otherwise a list of problems and exit code `2`; fix
them and run it again. Exit code `1` is something to fix in the command itself (one `ERROR:` line).

`push` runs the same check, using the layout the dataset is labelled with. A dataset with no layout
checks nothing.

**Next:** [Add data](dataset-upload.md) or [Release a version](dataset-release.md).
