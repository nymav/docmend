"""Orchestration: immutable snapshots -> graph -> changes -> findings -> guarded edits."""
from collections import Counter, defaultdict
from dataclasses import asdict

from .budget import Budget
from .changes import classify
from .adapters import SUPPORTED_SUFFIXES
from .codeparse import parse_code
from .config import Config
from .diagnosis import diagnose
from .docparse import parse_docs
from .gitstore import GitStore
from .mapping import build_index
from .models import DocMendError, Finding, Report
from .provider import ModelProvider
from .repair import validate_edit


def analyze_files(before: dict[str, str], after: dict[str, str], *, base: str = "fixture-base", head: str = "fixture-head", cfg: Config | None = None, provider: ModelProvider | None = None, semantic: bool = False, embedder=None, budget: Budget | None = None) -> tuple[Report, dict]:
    cfg = cfg or Config()
    budget = budget or Budget(cfg.analysis_timeout_seconds)
    budget.remaining()
    old_units, new_units = parse_code(before, review_duplicates=True), parse_code(after, review_duplicates=True)
    budget.remaining()
    old_docs, new_docs = parse_docs(before), parse_docs(after)
    old_index = build_index(old_units, old_docs, embedder=embedder if semantic else None, threshold=cfg.similarity_threshold)
    new_index = build_index(new_units, new_docs, embedder=embedder if semantic else None, threshold=cfg.similarity_threshold)
    budget.remaining()
    changes = classify(old_units, new_units)
    report = Report(base, head, new_index["fingerprint"], [{"kind": c.kind, "unit": c.unit.id, "path": c.unit.path, "line": c.unit.line, "before": asdict(c.before) if c.before else None, "after": asdict(c.after) if c.after else None} for c in changes])
    ambiguous_units = {u.id for u in [*old_units.values(), *new_units.values()] if u.kind == "ambiguous"}
    for unit_id in sorted(ambiguous_units):
        report.warnings.append(f"No documentation mapping certainty for repeated definition {unit_id}; active binding is not inferred and coverage is incomplete")
    for path in sorted(before.keys() | after.keys()):
        if before.get(path) != after.get(path) and not path.endswith(SUPPORTED_SUFFIXES):
            report.warnings.append(f"No documentation mapping: unsupported changed source {path}; coverage is incomplete")
    linked = defaultdict(set)
    for edge in old_index["links"] + new_index["links"]:
        linked[edge["unit"]].add(edge["section"])
    suspects = defaultdict(list)
    for change in changes:
        for sid in linked[change.unit.id]:
            if sid in new_docs:
                suspects[sid].append(change)
        if not linked[change.unit.id]:
            report.warnings.append(f"No documentation mapping for changed unit {change.unit.id}; coverage is incomplete")
    if len(suspects) > cfg.max_sections:
        raise DocMendError("Suspect-section budget exceeded; narrow the include/exclude patterns")
    names = Counter(u.name.rsplit(".", 1)[-1] for u in new_units.values())
    for sid in sorted(suspects):
        budget.remaining()
        group = suspects[sid]
        ambiguous = any(names[c.unit.name.rsplit(".", 1)[-1]] > 1 for c in group)
        finding, edit = diagnose(new_docs[sid], group, ambiguous=ambiguous, provider=provider)
        if edit:
            try:
                validate_edit(edit)
            except DocMendError as exc:
                finding.status = "review"
                finding.reason += f"; correction rejected: {exc}"
                edit = None
        report.findings.append(finding)
        if edit:
            report.edits.append(edit)
    # Coverage cannot be inferred from the number of mapped suspects alone.
    if not provider:
        report.warnings.append("Offline mode: behavioural and ambiguous changes are review findings, not LLM-verified decisions")
    budget.remaining()
    new_index["operations"] = {"elapsed_ms": budget.elapsed_ms(), "provider_requests": getattr(provider or embedder, "request_count", 0), "runtime_limit_seconds": cfg.analysis_timeout_seconds, "provider_request_limit": cfg.max_provider_requests}
    return report, new_index


def analyze_repository(store: GitStore, base_ref: str, head_ref: str, *, cfg: Config | None = None, llm: bool = False, semantic: bool = False) -> tuple[Report, dict, dict[str, str]]:
    store.budget = None  # A reused store starts a fresh analysis budget.
    base, head = store.resolve(base_ref), store.resolve(head_ref)
    # Read config from immutable base, not the untrusted PR working tree.
    cfg = cfg or store.trusted_config(base)
    budget = Budget(cfg.analysis_timeout_seconds)
    store.budget = budget
    provider = ModelProvider(cfg, budget=budget) if llm or semantic else None
    before, after = store.snapshot(base, cfg), store.snapshot(head, cfg)
    report, index = analyze_files(before, after, base=base, head=head, cfg=cfg, provider=provider if llm else None, semantic=semantic, embedder=provider, budget=budget)
    for path in store.uncovered_sources(base, head, cfg):
        warning = f"No documentation mapping: changed source {path} is outside configured adapters/includes; coverage is incomplete"
        if not any(path in w for w in report.warnings): report.warnings.append(warning)
    # The diff is evidence, not a command. Include only bounded code/document file hunks.
    changed_paths = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    changed, hunks = store.changed_lines(base, head, changed_paths)
    index["changed_hunks"] = hunks
    index["git_diff_sha256"] = __import__("hashlib").sha256(changed.encode()).hexdigest()
    budget.remaining()
    index["operations"]["elapsed_ms"] = budget.elapsed_ms()
    return report, index, after
