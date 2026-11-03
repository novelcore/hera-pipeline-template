# 1. You're in

**Goal:** you are signed in to the KAOS console and you know your organisation, your project, and
what your role lets you do.

**Who can do it:** anyone who has been invited to the organisation.

## Sign in

1. Open your organisation's console. Its address has the form `https://<org>.console.<platform domain>`.
   Your organisation admin sends it with the invitation e-mail.
2. Sign in with the account the invitation was sent to. KAOS has a single sign-in, and the same
   account later opens Argo, lakeFS, MLflow and `kaosctl`.
3. In the sidebar, open **Projects**. This lists the projects of your organisation. Open yours.

## What you should see

- Your organisation's name at the top of the sidebar.
- Your project under **Projects**. On the project page you see its environments, and buttons that
  open its dashboards and its **Datasets**.
- Under **Pipelines**, the ML apps of the projects you can see. [Chapter 2](2-your-apps.md) covers
  this page.

## What your role allows

You get a role by being a member of a **team**. A *project team* gives its role on one project. An
*organisation team* gives its role on every project of the organisation. Each team has one role,
and every member of the team has that role.

| role | Argo Workflows (runs) | GitHub (app repositories) | MLflow |
|---|---|---|---|
| `admin` | full control | admin | manage: create experiments, register and promote models |
| `ops` | submit, retry, stop runs | admin | signed in (verify the per-experiment rights) |
| `dev` | submit, retry, stop runs | maintain: push branches, open and merge pull requests | signed in (verify the per-experiment rights) |
| `business` | read only | triage: read, comment | signed in (verify the per-experiment rights) |

These rights come from the platform's own setup: the Argo SSO rules for each project role, the
GitHub team permission each role maps to, and MLflow's admin group. Pipelines log to MLflow with
the project's own machine account, which has admin rights, so a run's MLflow records never depend
on who submitted it. For datasets, lakeFS has no separate
rights per person. Everyone who can sign in to the project's lakeFS gets the same rights there
(verify which teams your project lets into lakeFS). Two rules apply to everyone: changes to a
dataset's `main` go only through a pull request, and only the owning project can write a dataset
([Datasets](../datasets.md)).

The console's **Identity & Access** page, under its **Roles** tab, shows "what each role can do, as
proven by the platform's end-to-end RBAC tests". If your role and the table above disagree, the
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

Access takes effect once the platform syncs the team. The console shows *"Committed, waiting for
platform sync."* in the meantime. Sign out and in again afterwards.

**Next:** [2. Your project's apps](2-your-apps.md).
