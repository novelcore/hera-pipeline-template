# 3. Install `kaosctl` and sign in

`kaosctl` is the command-line tool for your data. You use it on your own laptop to create, upload and release datasets. It comes from the Python package `kaos-lib`, the same package your steps use to read data.

## Do this

You need Python 3.9 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install \
  --index-url https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  "kaos-lib[zitadel]==0.4.0rc10"
kaosctl --version
```

Both index lines are needed: `kaos-lib` is on the first, its dependencies are on the second. The `==` pin is needed too, so pip does not pick another version.

Then go into the folder of your pipeline's code (see [step 5](05-create-your-pipeline.md); it holds a small settings file, `.kubecore/dataset-config.yaml`, that tells `kaosctl` where your project's data lives) and sign in:

```bash
kaosctl login
```

## You should now see

- `kaosctl --version` prints `kaosctl 0.4.0rc10` and the channel.
- `kaosctl login` opens your browser. Sign in, close the tab and go back to the terminal. The session is remembered, so every later command works without signing in again.

If a command says `ERROR: not signed in. Run kaosctl login ...`, sign in again.

!!! note "Which version?"
    The version above is the current pre-release. Stable releases arrive later and the install page lists the newest of each: [kaos-lib install](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/install.html). More in [kaos-lib versions](../kaos-lib-versions.md).

Next: [create a dataset and release v1](04-create-a-dataset.md).
