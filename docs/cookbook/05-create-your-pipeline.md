# 5. Create your pipeline

## Do this

1. In the console, open **Machine learning**, then **Pipelines**, then click **New pipeline**.
2. Move through the guided steps:
    1. **Name**: a short lowercase name, for example `cats-detector`.
    2. **Template**: the starting code. Choose **hera** for a plain starter you build on, or **yolo** for object detection. (hera is the scaffold; yolo is a ready-made template built on it.)
    3. **Project**: your project.
    4. **Where it runs**: the environment from [step 2](02-your-project.md).
    5. **Dataset**: the dataset to start with, for example `dataset-cats`.
    6. **Review**: check, then create.
3. Wait a minute or two, then open the new pipeline's page.

## You should now see

- Your pipeline in the **Pipelines** list.
- A link to its **code repository** on GitHub, and a link to its **run page**.
- Your code repository holds the starter files: `pipeline.py` (the list of steps), `config/` (your settings), and `steps/` (one folder of code per step). If you chose the hera scaffold you get one example step, `hello-world`.

Clone the code repository to your laptop:

```bash
git clone <the repository link from the pipeline page>
cd <the folder it created>
```

Your GitHub account needs access to the repository. If you cannot open it, ask your project administrator.

Next: [change a step and push](06-change-a-step.md).
