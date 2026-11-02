# development evaluation

| Method | Precision | Confirmed recall | Triage recall | Review burden | Repair correctness | Negative preservation |
|---|---:|---:|---:|---:|---:|---:|
| changed-file | 61.5% | 100.0% | 100.0% | 0.0% | — | 100.0% |
| changed-reference | 72.7% | 100.0% | 100.0% | 0.0% | — | 100.0% |
| docmend | 78.6% | 68.8% | 100.0% | 25.0% | 78.6% | 75.0% |

## Interpretation

Primary recall treats review/error as missed confirmed detections. Triage recall also credits review. Selective accuracy excludes review/error. Repair quality uses exact gold-section text; null means no proposals, not perfect quality. Wilson intervals treat sections as independent and are descriptive for these constructed fixtures.

## Case-level results

| Case | Truth | DocMend decision | Safe / correct repairs |
|---|---|---|---|
| dev-int | stale | stale | 1 / 1 |
| dev-string | stale | stale | 1 / 1 |
| dev-boolean | stale | stale | 1 / 1 |
| dev-keyword-only | stale | stale | 1 / 1 |
| dev-positional-only | stale | stale | 1 / 1 |
| dev-required-add | stale | stale | 1 / 1 |
| dev-parameter-remove | stale | stale | 1 / 1 |
| dev-annotated | stale | review | 0 / 0 |
| dev-config | stale | stale | 1 / 1 |
| dev-toml | stale | stale | 1 / 1 |
| dev-removed | stale | review | 0 / 0 |
| dev-behaviour | stale | review | 0 / 0 |
| dev-mixed | stale | review | 0 / 0 |
| dev-schema | stale | review | 0 / 0 |
| dev-comment | accurate | none | 0 / 0 |
| dev-format | accurate | none | 0 / 0 |
| dev-docstring | accurate | none | 0 / 0 |
| dev-already-updated | accurate | accurate | 0 / 0 |
| dev-intentional-override | accurate | review | 0 / 0 |
| dev-generic-prose | accurate | review | 0 / 0 |
| dev-unrelated-section | accurate | none | 0 / 0 |
| dev-doc-only | accurate | none | 0 / 0 |
| dev-unchanged | accurate | none | 0 / 0 |
| dev-override-same-section | stale | stale | 1 / 1 |
| dev-historical-label | accurate | stale | 1 / 0 |
| dev-historical-prose | accurate | stale | 1 / 0 |
| dev-hidden-comment | accurate | stale | 1 / 0 |
| dev-multiple-claims | stale | stale | 1 / 1 |

## Limits

Cases and labels are AI-authored constructed examples unless provenance explicitly states a real source snapshot. Source-backed mutation cases still use constructed documentation/changes. They are not natural historical documentation bugs or independently human-reviewed ground truth. No paid model was evaluated. Timing is warm local sequential execution, not concurrent-load performance.
