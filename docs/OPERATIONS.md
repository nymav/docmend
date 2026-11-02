# Operations and deployment

## Local and CI modes

1. **Offline audit** is the default. Reads Git blobs; writes analysis artifacts only.
2. **Model audit** requires `--llm` and trusted-base provider configuration. Code/doc evidence leaves the machine for that explicit provider. Configure the endpoint with the repository owner's approval.
3. **Semantic mapping** additionally requires `--semantic` and an actual embedding model.
4. **Local repair** is explicit. Safe edits must be reproducible from AST facts. Model drafts need `--include-drafts` after human review.
5. **GitHub publish** is explicit and never merges. Fork PRs remain read-only.

Keep the analysis action implementation pinned to an audited commit. Do not use a local action from an untrusted PR checkout with write tokens or API keys. The supplied consumer template has no secrets and never invokes repository scripts. Run DocMend from its own trusted installed package/image, not from code supplied by the target repository.

## Permissions

Read-only checks need `contents: read`. Publishing needs a token able to read the source PR and write repository contents plus pull requests/issues as applicable. Repository settings may need to allow GitHub Actions to create PRs. Token policy must be configured by the repository owner. The adapter is currently for github.com, not arbitrary enterprise API hosts. Use an Actions/GitHub App bot token for marker-comment upserts.

## Artifact handling

`index.json` contains source code and documentation text. Treat it with the same access controls as the repository. Default reports are local; workflow artifact upload is an explicit consumer choice. Reports contain no provider key values. Do not put credentials in source snippets; DocMend does not claim to be a secret scanner.

## Operational limits

Config bounds file count, per-file/total bytes, suspect sections and provider context. Git commands time out after 30 seconds. Provider HTTP requests time out according to config, use at most three attempts for selected transient statuses and refuse redirects. GitHub mutations are not automatically retried, because a timeout can occur after a write succeeds. Re-running publishing uses a head-specific branch and validates its tree/parent. A head change requires a fresh analysis.

If a branch was created but opening the PR failed, inspect that branch, then rerun with the same source head. DocMend never force-pushes it. Bot summaries are marker-updated; source PR comments from other authors are left alone. No summary may claim its code changes were merged or deployed.

## Recovery

Before removing a stale `.docmend-apply.lock`, verify no apply process is running and inspect the diff. Per-file writes are atomic; multi-file rollback is best effort. A concurrently edited file is not overwritten during rollback; manual recovery may be required. Recompute after source HEAD or documentation changes. Preserve the original report when investigating a rejected edit.

## Release gates still requiring a real environment

- Repeat the Docker smoke test in your target runner architecture (local ARM64 build and runtime have passed).
- Exercise provider/model compatibility with a repository owner-approved account and bounded spend.
- Run GitHub publishing on a sandbox same-repository PR and a read-only fork PR.
- Verify token/branch-protection settings and reruns against live GitHub.
- Pin the released image/action and third-party workflow actions to audited immutable digests/SHAs.
- Publish the Action/Marketplace listing only after reviewing release metadata and demo.

The public GitHub REST tree and PR schemas and Docker Action constraints were consulted on 2 November 2026:
- https://docs.github.com/en/rest/git/trees
- https://docs.github.com/en/rest/pulls/pulls
- https://docs.github.com/en/actions/reference/workflows-and-actions/dockerfile-support
- https://docs.github.com/en/actions/reference/security/secure-use

No live environment checks above are represented as completed by local mocks.
