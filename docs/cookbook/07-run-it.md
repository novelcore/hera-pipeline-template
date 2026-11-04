# 7. Run it and pick the dataset version

## Do this

1. In the console, open your pipeline's page and click the link to its **run page** (it is an Argo page; you only need the Submit button).
2. Click **Submit**. A form opens. This is the **run form**.
3. In the **dataset** dropdown pick a version, for example `dataset-cats@v1`.
4. Change any other field you want (every value from your `config/` folder is a field), or leave the defaults.
5. Optional: for each step you can pick a machine class and size.
6. Click **Submit**.

## You should now see

- The page switches to a live view. Every step is a box; it turns green when it finishes, red if it fails.
- Click a box, then its logs, to read what the step printed. For the example step you should see the dataset commit and the folder it read.
- Versions in the dataset dropdown are listed newest first, then `@latest`. A version you released a minute ago should be there. If not, see [when things go wrong](10-when-things-go-wrong.md).

See also [Run your pipeline](../run-it.md).

Next: [results, metrics and weights](08-see-results.md).
