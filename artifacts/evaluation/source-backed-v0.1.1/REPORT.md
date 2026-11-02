# source-backed evaluation

| Method | Precision | Confirmed recall | Triage recall | Review burden | Repair correctness | Negative preservation |
|---|---:|---:|---:|---:|---:|---:|
| changed-file | 50.0% | 100.0% | 100.0% | 0.0% | — | 100.0% |
| changed-reference | 66.7% | 100.0% | 100.0% | 0.0% | — | 100.0% |
| docmend | 100.0% | 50.0% | 100.0% | 25.0% | 100.0% | 100.0% |

## Interpretation

Primary recall treats review/error as missed confirmed detections. Triage recall also credits review. Selective accuracy excludes review/error. Repair quality uses exact gold-section text; null means no proposals, not perfect quality. Wilson intervals treat sections as independent and are descriptive for these constructed fixtures.

## Case-level results

| Case | Truth | DocMend decision | Safe / correct repairs |
|---|---|---|---|
| docatlas-changed-default | stale | stale | 1 / 1 |
| docatlas-docs-updated | accurate | accurate | 0 / 0 |
| docatlas-comment-only | accurate | none | 0 / 0 |
| docatlas-removed-function | stale | review | 0 / 0 |
| mailayer-changed-default | stale | stale | 1 / 1 |
| mailayer-docs-updated | accurate | accurate | 0 / 0 |
| mailayer-comment-only | accurate | none | 0 / 0 |
| mailayer-removed-function | stale | review | 0 / 0 |
| drax-tbs-changed-default | stale | stale | 1 / 1 |
| drax-tbs-docs-updated | accurate | accurate | 0 / 0 |
| drax-tbs-comment-only | accurate | none | 0 / 0 |
| drax-tbs-removed-function | stale | review | 0 / 0 |

## Limits

Cases and labels are AI-authored constructed examples unless provenance explicitly states a real source snapshot. Source-backed mutation cases still use constructed documentation/changes. They are not natural historical documentation bugs or independently human-reviewed ground truth. No paid model was evaluated. Timing is warm local sequential execution, not concurrent-load performance.
