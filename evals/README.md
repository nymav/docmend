# Evaluation protocol v1

This directory contains **28 development cases, 24 challenge cases and 12 source-backed controlled mutations**. These are deliberately small, inspectable inputs for the offline detector. They are not natural production bugs or independently human-reviewed labels.

## Provenance and separation

- `development.jsonl` and `challenge.jsonl` were frozen and committed before the first scoring run. SHA-256 values are in `manifest.json`.
- Development results were used to fix historical-signature and HTML-comment rewrites.
- Challenge scoring begins after the development fix is committed. The author and related syntax grammar are shared; call it a reserved challenge split, not a blind independent benchmark.
- `source-backed.jsonl` freezes isolated functions from three real local Git snapshots: DocAtlas, Mailayer and DRAX TBS. Commit IDs, paths, line ranges and source hashes are recorded. Documentation and mutations are constructed; no natural-history effectiveness claim follows.
- `load_cases` rejects duplicate IDs/input pairs, missing labels and labels outside the after-snapshot sections. Split checks reject identical input pairs crossing development/challenge.
- Labels and gold text were authored independently of the tool's returned decisions, using the stated code changes. They remain AI-assisted author labels pending independent human review.

## Units and methods

Each non-overlapping after-snapshot Markdown section is explicitly labelled stale or accurate. Source files are filtered using the default production config, including exclusion of tests. All sections must be labelled exactly once. A model is not involved.

1. **changed-file:** flag every doc section whenever any included Python/TOML text changes.
2. **changed-reference:** use the same AST change filter and explicit code-reference graph, then flag every linked section without validating the claim.
3. **docmend:** the full offline detector and guarded repair rules.

The reference baseline shares the AST mapper to isolate the benefit of diagnosis; it is not an independently engineered competing product. Neither baseline proposes repairs. `null` repair quality therefore means no proposals, not perfect correctness.

## Metrics and denominators

- Confirmed precision: true confirmed-stale decisions / all confirmed-stale decisions.
- Confirmed recall: true confirmed-stale decisions / all gold-stale sections. Review and operational failure remain misses in this denominator.
- Triage recall: gold-stale sections marked stale or review / all gold-stale sections.
- Review burden: sections sent for review / all sections. Review is an abstention, not a correct detection.
- Decision coverage/selective accuracy: exclude review and operational-error decisions explicitly.
- Repair exact match: proposed safe repairs matching the provided gold section / proposed safe repairs. This is a constrained gold-text check, not an independent semantic-quality judgment.
- Negative-section preservation: gold-accurate sections unchanged by repair / all gold-accurate sections.
- Operational error count is always reported; cases are not silently removed from the dataset.
- Latency is warm sequential in-process timing, repeated three times by default; no network, concurrent load or production throughput claim is made.

Wilson intervals are descriptive binomial intervals. Related constructed cases are not independent samples from production, so the intervals must not be presented as coverage guarantees for real repositories. Family-level counts and all case outputs remain available.

## Reproduce

```sh
PYTHONPATH=src python scripts/evaluate.py --split development --output artifacts/evaluation/development-v0.1.1
PYTHONPATH=src python scripts/evaluate.py --split challenge --output artifacts/evaluation/challenge-v0.1.1
PYTHONPATH=src python scripts/evaluate.py --split source-backed --output artifacts/evaluation/source-backed-v0.1.1
PYTHONPATH=src python scripts/coverage_report.py
```

`build_eval_cases.py` and `build_source_cases.py` refuse to overwrite frozen datasets. The source-case builder needs the original local repositories only when authoring a new dataset, not when reproducing the existing scores. Keep new natural-history, reviewer-adjudicated data separate from these development/challenge fixtures. Do not keep tuning on the same challenge results while calling them held out.

## Release gates

The scoring command exits 2 if any observed safe repair is incorrect or any section produces an operational error. These are engineering safety gates, not significance tests. Basic useful repairs are enforced by unit regressions, so abstaining on every task is not a sufficient replacement for the working detector.
