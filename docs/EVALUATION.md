# DocMend 0.1.1 — evaluation and validation report

3 November 2026. Runtime: Python 3.12.14. Offline detector; no paid model calls.

## What improved

The expanded development evaluation found three incorrect automatic repairs in 0.1.0: two historical signatures and a declaration in a hidden HTML comment. The fix excludes historical declarations and HTML comments from automatic repair. It was developed against development cases, then committed before challenge scoring. The detector files are unchanged from freeze commit `4685e3ef788f3c2c225c56aec37622d4df57aca8` after the challenge results were seen.

| Development measure | Before fix | After fix |
|---|---:|---:|
| Confirmed true positives | 11 | 11 |
| False confirmed alarms | 3 | 0 |
| Correct / proposed repairs | 11/14 | 11/11 |
| Accurate sections preserved | 75.0% | 100.0% |

## Detection versus deferral

| Split | Sections (stale / accurate) | Confirmed TP / FP / FN | Confirmed recall | Review sections | Correct / proposed repairs |
|---|---|---|---:|---:|---|
| development | 28 (16 / 12) | 11 / 0 / 5 | 68.8% | 10 | 11/11 |
| challenge | 24 (14 / 10) | 8 / 0 / 6 | 57.1% | 11 | 8/8 |
| source-backed | 12 (6 / 6) | 3 / 0 / 3 | 50.0% | 3 | 3/3 |

On the reserved challenge split, 8 of 14 gold-stale sections were confirmed and repaired; the other 6 were deferred to review. Five accurate sections were also sent for review, for 11/24 reviews overall. All 10 accurate sections remained unchanged. Zero false confirmed alarms occurred in this small set. This demonstrates conservative repair, not complete semantic detection.

## Challenge baselines

| Method | TP | FP | Confirmed recall | Review burden | Repair output |
|---|---:|---:|---:|---:|---|
| changed-file | 14 | 9 | 100.0% | 0.0% | None |
| changed-reference | 14 | 6 | 100.0% | 0.0% | None |
| docmend | 8 | 0 | 57.1% | 45.8% | 8/8 gold-exact |

The file/reference baselines have higher automatic recall but more false alarms. DocMend trades automatic coverage for precision and manual triage; this is not an unconditional superiority claim. Its 8/8 repair exact-match result has a descriptive Wilson 95% interval of approximately 67.6%–100%, and related constructed cases do not justify generalizing that interval to production.

## Implementation tests and coverage

- 73 tests passed locally, with zero failures or errors.
- Executable-line coverage: 1003/1105 = 90.77%. Instrumentation: standard-library tracing and compiled code-object line tables. Branch coverage is not measured.
- The pinned-base Docker image was rebuilt; the expanded suite is run with network disabled and a read-only source mount.
- Version 0.1.1 wheel builds and installs offline.
- The previous GitHub CI run for 0.1.0 succeeded; the expanded CI workflow now includes all three evaluation splits and coverage.

## Scope and remaining evidence needs

All 52 primary cases and labels are AI-assisted constructions. The 12 source-backed cases use actual isolated functions from pinned DocAtlas, Mailayer and DRAX TBS snapshots, but the documentation and changes are constructed. They do not represent 12 naturally occurring production bugs. There is no independently human-reviewed or blind external test set yet.

The evaluation covers functions/defaults, schemas/config, removals, behavioural changes, comments/formatting, already-updated docs, overrides, history, hidden comments, routes/CLI declarations, fenced/multiline signatures and ambiguous/multiple symbols. The scorer keeps operational failures and abstentions explicit.

The offline detector did not automatically repair route changes, CLI renames, fenced/multiline declarations, multiple changed symbols in one section or ambiguous class methods in the challenge set. These remain documented development directions; the challenge set must not be reused as an untouched holdout after tuning on them.

Next independent evidence should come from natural code/doc commit pairs, reviewer-adjudicated labels and live provider/GitHub evaluation. No paid-model performance or end-to-end live GitHub publishing result is claimed.

## Reproduction

See `evals/README.md`. Raw case-level outputs, family summaries, exact data/software hashes, timing and descriptive intervals are in `artifacts/evaluation/`. Engineering release gates fail on any observed incorrect safe repair or operational error; they are not statistical guarantees.
