# Validation record — 2 November 2026

**Release status: validated local pilot. Live provider/GitHub integration and public release remain pending.**

| Check | Actual result |
|---|---|
| Host Python | 3.12.14 |
| Unit + integration suite | 51 passed, zero failed |
| Same suite inside Docker | 51 passed; network disabled; source mounted read-only |
| Constructed development fixtures | 12/12 expected status/repair outcomes; not a held-out human-reviewed benchmark |
| Wheel build | `docmend-0.1.0-py3-none-any.whl` |
| Isolated installation | Installed offline into a new venv; CLI returned 0.1.0 |
| Docker image | Built from the pinned official Python base; local Linux ARM64 |
| Actual Docker Action entrypoint | Detected 1 stale declaration / 1 safe edit; exit 2, as designed |
| Docker guarded apply | Repaired only README.md in isolated fixture; exit 0 |
| Docker original-base recheck | 0 stale / 1 matching declaration; exit 0 |
| YAML syntax | Action, CI and consumer template parsed successfully |
| GitHub publishing | Mock tests cover same-repo/stale-head guards and branch/PR/comment reruns; no live write |
| LLM/embedding adapters | Contract, invalid output, budget, redirect and retry tests; no live provider request |

## Real repository experiment

A local snapshot of DocAtlas at commit `0688998769e3abaddaf828a8dd779d6905a064fc` was copied into an isolated repository. The controlled edit changed the actual `src/docatlas/evaluation.py::evaluate` default `k` from 5 to 6. A deliberately added documentation fixture declared its exact signature.

Before repair: one confirmed stale declaration, one other review finding, one safe edit. After applying that edit and comparing the repaired head to the **original base**: zero confirmed stale declarations, one matching declaration and the other review finding retained. No code in the source DocAtlas checkout was modified. This is a controlled integration test, not a remote fork or an estimate of production accuracy.

Evidence: `artifacts/docatlas-integration/run.json`, `before-repair/`, `after-repair/`; container evidence under `artifacts/container-smoke/`. The 12 development fixtures test status/repair conformance, not generalized precision or recall. Reported `review` is an abstention/manual triage outcome.

## Important design checks exercised

- Comment/whitespace/docstring-only changes do not create semantic changes.
- A literal argument in a usage example is not automatically treated as a default declaration.
- Model self-confidence cannot promote a rewrite to safe mode.
- Invalid model JSON or failed second-pass review yields an error or unresolved review, not a clean result.
- Edits preserve headings, code fences, links and newline convention.
- Stale, forged, overlapping, out-of-range and path-escaping repairs are refused.
- Git symlink blobs and symlink write targets are refused.
- Apply uses a lock, file hashes, per-file atomic replacement and rollback on write failure.
- Config is read from the base commit; code in the target repository is not executed.
- Fork secret/publish modes and pull_request_target are refused by the action.

## Not yet established

No broad semantic-accuracy guarantee, independent human-reviewed benchmark, production load test, live paid-model compatibility, live GitHub permissions exercise, amd64 runner validation, Marketplace listing or remote PR walkthrough video is claimed. Auto-merge is intentionally not implemented. These distinctions are recorded per source task in REQUIREMENTS.md.
