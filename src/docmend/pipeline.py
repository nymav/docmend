"""Orchestration: immutable snapshots -> graph -> changes -> findings -> guarded edits."""
from collections import Counter, defaultdict
from dataclasses import asdict

from .changes import classify
from .codeparse import parse_code
from .config import Config
from .diagnosis import diagnose
from .docparse import parse_docs
from .gitstore import GitStore
from .mapping import build_index
from .models import DocMendError, Finding, Report
from .provider import ModelProvider
from .repair import validate_edit


def analyze_files(before: dict[str, str], after: dict[str, str], *, base: str = "fixture-base", head: str = "fixture-head", cfg: Config | None = None, provider: ModelProvider | None = None, semantic: bool = False, embedder=None) -> tuple[Report, dict]:
    cfg = cfg or Config()
    old_units, new_units = parse_code(before), parse_code(after)
    old_docs, new_docs = parse_docs(before), parse_docs(after)
    old_index = build_index(old_units, old_docs, embedder=embedder if semantic else None, threshold=cfg.similarity_threshold)
    new_index = build_index(new_units, new_docs, embedder=embedder if semantic else None, threshold=cfg.similarity_threshold)
    changes = classify(old_units, new_units)
    report = Report(base, head, new_index["fingerprint"], [{"kind": c.kind, "unit": c.unit.id, "path": c.unit.path, "line": c.unit.line, "before": asdict(c.before) if c.before else None, "after": asdict(c.after) if c.after else None} for c in changes])
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
    return report, new_index


def analyze_repository(store: GitStore, base_ref: str, head_ref: str, *, cfg: Config | None = None, llm: bool = False, semantic: bool = False) -> tuple[Report, dict, dict[str, str]]:
    base, head = store.resolve(base_ref), store.resolve(head_ref)
    # Read config from immutable base, not the untrusted PR working tree.
    cfg = cfg or store.trusted_config(base)
    provider = ModelProvider(cfg) if llm or semantic else None
    before, after = store.snapshot(base, cfg), store.snapshot(head, cfg)
    report, index = analyze_files(before, after, base=base, head=head, cfg=cfg, provider=provider if llm else None, semantic=semantic, embedder=provider)
    # The diff is evidence, not a command. Include only bounded code/document file hunks.
    changed_paths = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    changed, hunks = store.changed_lines(base, head, changed_paths)
    index["changed_hunks"] = hunks
    index["git_diff_sha256"] = __import__("hashlib").sha256(changed.encode()).hexdigest()
    return report, index, after
