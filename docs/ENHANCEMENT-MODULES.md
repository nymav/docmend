# Seven enhancement modules — implementation status

Offline implementation is complete for the bounded scope below. Live validation is explicitly deferred because the owner confirmed no provider credentials, App installation token or independently reviewed dataset is available. This is not a claim that all possible DocMend features or production validation are complete.

| Module | Implemented enhancement | Verification |
|---|---|---|
| 1. Action and release | Early input validation; repository-identity fork detection; App bot input; bounded, serialized consumer workflow | Entrypoint integration and refusal tests; Python/container CI |
| 2. Source understanding | Opt-in JSON config adapter with source spans, JSON Pointer IDs and canonical contracts; duplicate/nonfinite rejection; unsupported/excluded changed-source coverage warnings | Parser, formatting-negative, static repair and real Git snapshot tests |
| 3. Evidence and diagnosis | Historical snapshot preparation; frozen input/pattern fingerprints; two distinct reviewer declarations and label agreement; gold repairs; positive/negative benchmark gate; existing abstention metrics and baselines | Unreviewed, mutated-input, repeated-reviewer and mismatch rejection tests |
| 4. Repair safety | Durable private journal before writes; fsynced atomic replacement; explicit crash rollback; complete preflight conflict checks; unresolved-journal apply lockout | Real child-process crash, multi-file failure, post-rename failure and conflict tests |
| 5. Review and interoperability | SARIF 2.1.0, stable fingerprints, confirmed/review separation, actual source regions and analysis-limit notices; existing import-only dashboard retained | SARIF URI/status/span tests and dashboard regression suite |
| 6. GitHub collaboration | Recheck source PR open state/SHAs before exposed mutations; no force update; app-owned summary matching; fail-closed ref races; bounded read-only installation-token probe | Idempotent rerun, changed/closed source PR, other-bot, two-writer/ref race tests; fake App transport |
| 7. Operations and evaluation | Monotonic runtime checkpoints, Git/provider timeout bounds, aggregate provider-attempt cap, measured index telemetry; explicit live provider probe using synthetic public evidence | Deadline/request-count/config tests; frozen development/challenge/source-backed evaluations |

## Commands

```sh
# JSON adapter: add '*.json' to trusted base include patterns, then run normal check.
docmend check --repo REPO --base BASE --head HEAD

# Stop ALL repair/recovery writers first. Explicitly roll back an interrupted apply.
docmend recover --repo REPO --confirm-no-active-writer

# Export actual immutable historical snapshots, leaving labels blank.
PYTHONPATH=src python scripts/reviewed_benchmark.py prepare --repo REPO --base BASE --head HEAD --author PREPARER --output review-queue.jsonl
# Human annotators fill every label (stale boolean and rationale), gold_files,
# and two reviews with reviewer, input_sha256 and matching labels.
PYTHONPATH=src python scripts/reviewed_benchmark.py score --dataset reviewed.jsonl --output reviewed-results.json

# Requires a locally configured DOCMEND_APP_TOKEN. Read-only; write rights untested.
PYTHONPATH=src python scripts/validate_github_app.py --repository OWNER/REPO
# Requires provider config and its environment key. May incur charges; opt-in required.
PYTHONPATH=src python scripts/validate_provider.py --config CONFIG.toml --allow-provider-request
```

Review identities are self-declared; the software cannot verify their independence. Label agreement is an audit gate, not proof of annotation quality. A synthetic test with reviewer declarations is not human-reviewed evidence.

Runtime limits are cooperative at CPU stage boundaries; Git and HTTP calls have bounded timeouts. A GitHub job timeout is the hard outer process bound. `index.json.operations` records elapsed time and actual provider attempt count. No production SLA is inferred from small sequential fixture timings.

Journal files contain original documentation and must remain private. Recovery confirmation asserts no other writer is active; it does not terminate processes. Conflicting user edits cause refusal and leave the journal for manual recovery. Ordinary filesystems do not provide an atomic multi-file transaction.

Publishing lifecycle: one writer per repository/source PR; use workflow concurrency (do not cancel active publishing jobs). Source closed/merged/moved => recompute or stop. A ref race fails closed; rerun verifies the winning branch. Repair PRs remain drafts and are never merged or deleted automatically. GitHub APIs do not provide an atomic branch/PR/comment transaction; ambiguous mutation failures require inspection.

## Deferred external evidence

- Actual independently human-reviewed historical cases and results.
- Actual provider/embedding compatibility and model-quality evaluation.
- Actual GitHub App installation/write-permission validation.
- Marketplace Developer Agreement acceptance by owner.

All corresponding offline tooling is implemented; none of these external outcomes is fabricated.
