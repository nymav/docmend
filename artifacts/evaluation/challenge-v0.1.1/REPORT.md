# challenge evaluation

| Method | Precision | Confirmed recall | Triage recall | Review burden | Repair correctness | Negative preservation |
|---|---:|---:|---:|---:|---:|---:|
| changed-file | 60.9% | 100.0% | 100.0% | 0.0% | — | 100.0% |
| changed-reference | 70.0% | 100.0% | 100.0% | 0.0% | — | 100.0% |
| docmend | 100.0% | 57.1% | 100.0% | 45.8% | 100.0% | 100.0% |

## Interpretation

Primary recall treats review/error as missed confirmed detections. Triage recall also credits review. Selective accuracy excludes review/error. Repair quality uses exact gold-section text; null means no proposals, not perfect quality. Wilson intervals treat sections as independent and are descriptive for these constructed fixtures.

## Case-level results

| Case | Truth | DocMend decision | Safe / correct repairs |
|---|---|---|---|
| challenge-float | stale | stale | 1 / 1 |
| challenge-none | stale | stale | 1 / 1 |
| challenge-escaped-string | stale | stale | 1 / 1 |
| challenge-async | stale | stale | 1 / 1 |
| challenge-varargs | stale | stale | 1 / 1 |
| challenge-negative | stale | stale | 1 / 1 |
| challenge-toml-bool | stale | stale | 1 / 1 |
| challenge-toml-string | stale | stale | 1 / 1 |
| challenge-route | stale | review | 0 / 0 |
| challenge-cli | stale | review | 0 / 0 |
| challenge-fenced-declaration | stale | review | 0 / 0 |
| challenge-multiline-declaration | stale | review | 0 / 0 |
| challenge-two-symbols | stale | review | 0 / 0 |
| challenge-qualified-collision | stale | review | 0 / 0 |
| challenge-deprecated-history | accurate | review | 0 / 0 |
| challenge-old-example | accurate | review | 0 / 0 |
| challenge-comment-block | accurate | none | 0 / 0 |
| challenge-already-updated-async | accurate | accurate | 0 / 0 |
| challenge-return-still-valid | accurate | review | 0 / 0 |
| challenge-removed-mentioned-as-removed | accurate | review | 0 / 0 |
| challenge-unrelated-module | accurate | none | 0 / 0 |
| challenge-tests-only | accurate | none | 0 / 0 |
| challenge-annotation-format | accurate | none | 0 / 0 |
| challenge-hidden-previous | accurate | review | 0 / 0 |

## Limits

Cases and labels are AI-authored constructed examples unless provenance explicitly states a real source snapshot. Source-backed mutation cases still use constructed documentation/changes. They are not natural historical documentation bugs or independently human-reviewed ground truth. No paid model was evaluated. Timing is warm local sequential execution, not concurrent-load performance.
