# 1. You're in

**Goal:** you are signed in to the KAOS console and you know your organisation, your project, and
what your role lets you do.

**Who can do it:** anyone who has been invited to the organisation.

## Sign in

1. Open your organisation's console. The link is in the invitation e-mail your organisation admin sent.
2. Sign in with the account the invitation was sent to. KAOS has a single sign-in, and the same
   account later opens the run page, lakeFS, MLflow and `kaosctl`.
3. In the sidebar, open **Projects**. This lists the projects of your organisation. Open yours.

## What you should see

- Your organisation's name at the top of the sidebar.
- Your project under **Projects**. On the project page you see its environments, and buttons that
  open its dashboards and its **Datasets**.
- Under **Pipelines**, the pipelines of the projects you can see. [Chapter 2](2-your-apps.md) covers
  this page.

## What your role allows

You get a role by being a member of a **team**. A *project team* gives its role on one project. An
*organisation team* gives its role on every project of the organisation. Each team has one role,
and every member of the team has that role.

| role | Runs | GitHub (app repositories) | MLflow |
|---|---|---|---|
| `admin` | full control | admin | manage: create experiments, register and promote models |
| `ops` | submit, retry, stop runs | admin | signed in (verify the per-experiment rights) |
| `dev` | submit, retry, stop runs | maintain: push branches, open and merge pull requests | signed in (verify the per-experiment rights) |
| `business` | read only | triage: read, comment | signed in (verify the per-experiment rights) |

Pipelines record their results in MLflow under your project's own account, so a run's MLflow
records do not depend on who submitted it. In lakeFS, everyone who can sign in to your project's
lakeFS has the same rights there. Two rules apply to everyone: changes to a dataset's `main` go only
through a pull request (a proposed change that must be accepted), and only the owning project can
write a dataset ([Datasets](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/datasets.html)).

The console's **Identity & Access** page, under its **Roles** tab, shows "what each role can do". If your role and the table above disagree, the
console page is right.

To work through this cookbook you need `dev`, `ops` or `admin` on your project.

## If you don't see your project

You are not on a team that has access to it yet. The console shows *"No access until added to a
team"* for a member in that state.

- **Who adds you:** an **organisation admin**. **Identity & Access** appears in the sidebar only for
  organisation admins.
- **What they do:** under **Identity & Access**, the **Members** tab has **Invite member** for
  someone who is not in the organisation yet. Under the **Teams** tab, they open the team (or use
  **Create team**, then pick the role and the scope: the organisation, or one project), then choose
  **Manage team**, then **Add members**.
- **If it still doesn't work:** the team links people by the **e-mail of their sign-in account**. A
  different e-mail, for example a personal one, does not match. Give your admin the exact address
  you sign in with.

Access takes effect a few minutes after the team is saved. The console shows *"Committed, waiting for
platform sync."* in the meantime. Sign out and in again afterwards.

**Next:** [2. Your project's apps](2-your-apps.md).
