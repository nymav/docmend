# DocMend

Evidence-bound documentation maintenance for Python repositories. DocMend compares two immutable Git commits, maps changed code to Markdown sections, diagnoses drift and proposes narrowly scoped repairs. A Docker GitHub Action and an installable Python CLI expose the same modules.

**Version 0.3.0 is a prerelease pilot, not a production certification.** See [validation and remaining release gates](docs/VALIDATION.md). The runtime has no third-party Python dependencies. Python 3.11+ and Git are required; local validation uses Python 3.12.

## What happens when a default changes?

```python
# Before                    # After
# def fetch(url, timeout=30) # def fetch(url, timeout=60)
```

Documentation written as **Signature:** followed by the code span `fetch(url, timeout=30)` receives a targeted correction. An example that explicitly chooses `timeout=30` may remain valid; DocMend does **not** automatically change it. Ambiguous, behavioural and model-generated changes require review.

## Run it now, without keys

From this directory:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python scripts/demo.py --output artifacts/demo
```

Open `artifacts/demo/before-repair/summary.md`, `safe.patch` and `report.json`, then compare the report under `after-repair/`. The demo creates an isolated temporary Git repository and never modifies your source repository.

Install the CLI:

```sh
python -m pip install .
docmend --version
docmend check --repo /path/to/repository --base BASE_COMMIT --head HEAD
```

The base and head commits must exist locally. The analysis uses Git blobs, not uncommitted working-tree code. Config is read from `.docmend.toml` at the **base** commit; untrusted PR config cannot redirect provider traffic. Start with `.docmend.example.toml`, edit it and commit it before using it as a trusted base.

## Commands

| Command | Purpose |
|---|---|
| `index --base SHA --head SHA` | Persist code units, document sections, graph links and changed-line evidence |
| `check --base SHA --head SHA` | Diagnose drift and write JSON, Markdown and patch artifacts |
| `apply --report path/report.json` | Recompute static evidence, verify HEAD/file hashes, then apply safe edits locally |
| `apply --report ... --include-drafts` | Explicitly apply reviewed model drafts; retains structural and file-hash checks |
| `publish --base SHA --head SHA --repository owner/repo --pr N` | Recompute analysis, create/reuse a draft repair PR and post/update a summary |

Use `--repo` on every command when analyzing another checkout. `--output` is repository-relative, default `.docmend/report`. Paths escaping the repository and symlink outputs are refused. Exit codes: **0** = no blocking finding, **2** = drift/review/coverage finding, **3** = operational error. `check --fail-on stale` blocks only confirmed staleness; `--fail-on never` writes a report without gating CI. Neither option turns an operational failure into success.

`apply` refuses stale reports, modified documentation and forged “safe” edits that cannot be reproduced from code facts. Repairs now persist a private `.docmend-recovery.json` journal before writing. If interrupted, stop all writers and run `docmend recover --repo REPO --confirm-no-active-writer`. Recovery refuses conflicting user edits and preserves the journal. Writes are atomic per file, with rollback; this is not an atomic multi-file transaction.

## Modules

See [module contracts and data flow](docs/MODULES.md). Parsers, graph mapping, diff classification, diagnosis, repair validation, reporting, provider integration, GitHub publishing and CLI orchestration are separate importable modules.

## Optional model/embedding support

Commit an explicit HTTPS endpoint and provider-supported model IDs in trusted base config. Set the referenced environment key, then opt in:

```sh
docmend check --repo /path/to/repository --base BASE_COMMIT --llm
# Add --semantic only when a real embedding model is configured.
```

The adapter supports chat-completion-compatible JSON endpoints and embedding endpoints. It enforces bounded requests, timeouts, response shapes and rate-limit retries. A model diagnosis is followed by a separate correction request and a second validation pass. Even a passed second model review yields a **draft**, never an automatically approved repair. Live paid-provider compatibility has not been exercised in this build; contract tests use explicit fake transports.

Explicit symbol mapping works offline. Semantic mapping requires real vectors; the tool never substitutes hash vectors and calls them embeddings. The graph is JSON rather than a vector database because this bounded per-commit workload does not need a separate storage service. It is rebuilt from the analyzed commits, avoiding reuse of a stale mapping.

## GitHub integration

[Action metadata](action.yml), [Dockerfile](Dockerfile) and [consumer workflow template](examples/workflows/doc-check.yml) are included. The consumer template uses `nymav/docmend@v0.3.0`; pin an audited full commit SHA for production. The template uses read-only PR analysis and uploads the report.

Publishing is **off by default**. It requires an explicitly supplied write token and an open, same-repository PR whose base/head SHAs still match. It creates a separate draft PR **into the source feature branch**, avoiding inclusion of unrelated feature changes in a docs PR against main. Reruns verify the existing branch tree and parent rather than force-pushing. Summary comments are updated when a bot-owned marker is found. PAT-authored comments are not treated as bot comments; use a GitHub App/Actions token for stable comment upserts.

Forks are read-only. `pull_request_target` is refused. Do not run PR-controlled local action code with secrets. Auto-merge is intentionally unsupported in this release; a high model confidence score is not proof that merging a change is safe. See [operations](docs/OPERATIONS.md).

## Evidence and scope

- `artifacts/demo/fixture-evaluation.json`: 12 constructed development cases. Review is tracked separately from confirmed staleness; these are not a held-out human-reviewed accuracy benchmark.
- `artifacts/docatlas-integration/`: real DocAtlas source snapshot, a controlled numeric-default change, an added declaration fixture, guarded repair and original-base recheck. Existing review findings remain visible.
- [Requirements matrix](docs/REQUIREMENTS.md): all 18 guide steps mapped to implementation, deliberate changes and pending release work.

Supported semantic inputs: Python AST, module-level uppercase config assignments and TOML keys. Python function signatures, class schemas, endpoint decorators and common CLI decorators are inspected statically. Markdown/MDX section boundaries are fence-aware. Complex dynamic configuration, runtime-discovered APIs, arbitrary languages, semantic entailment of all prose and undocumented features are outside automatic-repair guarantees.

## Expanded evaluation (0.1.1)

[Full evaluation report](docs/EVALUATION.md): 73 passing tests, about 90.8% executable-line coverage, 28 development + 24 reserved challenge + 12 source-backed mutation cases. The expanded development set exposed three wrong automatic repairs; these were fixed before challenge scoring. On the challenge split, 8/14 stale sections were automatically confirmed and repaired, six were deferred, and all ten accurate sections were unchanged. Eleven sections in total needed review. These are constructed cases, not a human-reviewed real-world accuracy estimate.

```sh
PYTHONPATH=src python scripts/evaluate.py --split challenge --output artifacts/evaluation/challenge-v0.1.1
PYTHONPATH=src python scripts/coverage_report.py
```

## Validation

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python scripts/demo.py --output artifacts/demo
python -m pip wheel --no-deps --no-build-isolation --wheel-dir artifacts/dist .
```

CI includes Python 3.11/3.12/3.13 and a Docker build. Those remote jobs are configured, not asserted to have run locally. The pinned-base Docker image built successfully and the full suite passed inside it with networking disabled; the actual Action entrypoint was also smoke-tested locally. No external GitHub writes, model requests or Marketplace publication were performed.

MIT licensed. Source requirement: BASWE, *15 AI Engineering Projects That Actually Land Jobs*, Project 4, pages 11–13. The guide itself is not bundled or relicensed in this code repository.

## 0.2.0 release improvements

Every analysis now writes `report.sarif` alongside existing artifacts. The Action exposes its path as `outputs.sarif`. Confirmed stale sections are errors; unresolved reviews are warnings, and analysis limits remain visible. Uploading to code scanning is optional and requires separate `security-events: write` permission. SARIF does not imply security vulnerability detection.

See [the seven enhancement modules and remaining gates](docs/ENHANCEMENT-MODULES.md). Action inputs reject invalid gate values and multiline output paths before analysis. Live-provider and independently annotated real-world evaluation remain pending.

## 0.3.0 — seven-module implementation

Opt-in JSON configuration analysis, real source regions in SARIF, independent-review dataset preparation/scoring, durable crash recovery, PR lifecycle/race guards, App-owned comment matching, runtime/request budgets and explicit live compatibility probes are implemented. See [module contracts, commands and deferred external evidence](docs/ENHANCEMENT-MODULES.md). Python/TOML remain default inputs; JSON requires trusted include patterns. Unsupported changed source is reported as incomplete coverage.

`index.json.operations` records elapsed analysis time and provider attempts. Live API credentials and human-reviewed cases are not available, so those external validation gates remain unrun.
