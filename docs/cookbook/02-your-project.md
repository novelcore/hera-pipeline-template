# 2. Your project and where pipelines run

## Do this

1. In the console, open **Projects** and click your project.
2. Look at the list of **environments**.

## You should now see

An environment is a place your project can run work. Some are in the cloud, some are supercomputer queues. For a pipeline you only need to know one thing: **which environment it runs on**. You pick that when you create the pipeline ([step 5](05-create-your-pipeline.md)).

Open **Machines** under **Machine learning** to see the machine kinds each environment offers, for example CPU only or with a GPU. A machine kind is called a **class**. On a supercomputer environment the kind is shown as "Slurm" and the provider in brackets, for example "Slurm (MeluXina)", and the classes look like `meluxina-gpu`. That is only a name; you choose a class per step on the run form.

!!! tip "Not sure which one to pick?"
    Take the default. You can change the class of any single step later on the run form without touching your code.

Next: [install `kaosctl` and sign in](03-install-kaosctl.md).
