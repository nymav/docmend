# Running DocMend on GitHub

The **Documentation drift** workflow checks every pull request in this repository.
It compares immutable PR base/head commits, displays findings on the Actions run
summary and uploads JSON reports, indexes and proposed patches as an artifact.
Confirmed stale documentation fails the check; review-only findings remain visible
without blocking. Operational failures also fail the check. This is not configured
as a required branch-protection check.

## Run it yourself

1. Open this repository on GitHub, then **Actions → Documentation drift**.
2. Select **Run workflow**, leave the workflow branch as **main**.
3. Enter a base and head Git reference. Defaults compare `HEAD~1` with `HEAD`.
4. Open the completed run to read its summary. Download **documentation-report**
   for the patch and full JSON evidence.
5. Manual runs also upload **documentation-demo**, showing one stale signature,
   its guarded repair and the passing recheck in an isolated temporary repository.

A comparison with no changed code may correctly report zero findings. The separate
constructed demo illustrates a positive detection; it is not evidence of drift in
the repository you selected.

## Permissions and scope

The analyzer is pinned to audited commit
`461db9acd6d192c5a63a4b1fdfa10fcf75c43a8f` in a separate checkout. Target code is
read as Git data, never installed or imported. No provider key or write token is
configured, no model requests are made, and no repair commits or PRs are created.
Only read permission is requested. Artifacts expire after seven days.

This workflow operates on **DocMend itself**. To enable another repository,
explicitly configure access to the private engine repository and pin its audited
commit; the example consumer workflow remains a template. A private repository
can consume GitHub Actions allowance. No always-running server or web dashboard
is deployed by this workflow.
