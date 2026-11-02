# P04 source requirement coverage

Source: BASWE Project 4, PDF pages 11–13. “Implemented” below means code and local validation exist, not that external services have been deployed.

| Source task | Implementation / evidence | Status / deliberate difference |
|---|---|---|
| F01-T01 semantic code chunks | `codeparse`; AST functions/classes, routes/config/CLI decorators | Python/TOML supported; dynamic runtime discovery not guaranteed |
| F01-T02 doc sections | `docparse`; fence-aware exact spans and heading paths | Implemented; heading tests |
| F01-T03 link graph | `mapping`; explicit refs + real provider embeddings | Offline refs tested; embedding contract tested, live endpoint pending |
| F01-T04 persistent graph | `reporting.save` -> `index.json` | Implemented; JSON rebuilt from analyzed commits instead of stale cache reuse |
| F02-T01 Git diff/hunks | `gitstore` + pipeline; before/after blobs, changed hunks | Implemented with scope and size budgets |
| F02-T02 meaningful changes | `changes`; AST contracts/body hashes | Comments/format/docstrings ignored; behavioural equivalence of body refactors is not assumed |
| F02-T03 affected sections | union of old/new graph links | Implemented; unmapped changes are coverage gaps |
| F02-T04 LLM verification | `provider` + `diagnosis` strict status schema | Implemented and mocked; opt-in real-model validation pending |
| F03-T01 targeted corrections | static declarations + bounded section generation | Implemented; explicit override examples are review-only |
| F03-T02 second correction pass | distinct model audit + structural/hash guards | Implemented; model agreement alone never grants safe mode |
| F03-T03 confidence/review modes | `safe` and `draft`; model self-rating separate | No confidence-based auto-merge; complex changes require review |
| F04-T01 Docker action metadata | `Dockerfile`, `action.yml`, `entrypoint.py` | Packaged; Docker image, full in-container suite and entrypoint smoke test passed locally. Auto-merge intentionally unsupported |
| F04-T02 correction PR / review comments | `github` + explicit `publish` command | Mocked same-repo PR/rerun tests; live token integration pending |
| F04-T03 summary | JSON/Markdown, step summary, bot-marker comment upsert | Local action entrypoint tested; live remote write not exercised |
| F05-T01 real-repo test | local DocAtlas snapshot with controlled default change | Done locally; no remote fork or live Action installation |
| F05-T02 measure outcomes | 12 constructed fixtures + recorded DocAtlas run | Status/repair conformance reported; not a held-out accuracy benchmark |
| F06-T01 installation / marketplace | wheel builds, CLI, Action package | Local package validation; Marketplace not published |
| F06-T02 demo | reproducible demo script, reports and patches | Local executable walkthrough; remote PR video not recorded |
