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


def docstring_sections(files: dict[str, str], units: dict) -> dict:
    """One section per function/class docstring, keyed '<path>::<name>#docstring'."""
    import ast
    from .models import Section, digest
    sections = {}
    for path, text in files.items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError):
            continue
        lines = text.splitlines(keepends=True)
        def visit(node, prefix=""):
            for child in getattr(node, "body", []):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = prefix + child.name
                    first = child.body[0] if child.body else None
                    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str) and f"{path}::{name}" in units:
                        sid = f"{path}::{name}#docstring"
                        sections[sid] = Section(sid, path, f"{name} docstring", first.lineno - 1, first.end_lineno, "".join(lines[first.lineno-1:first.end_lineno]), digest(text))
                    if isinstance(child, ast.ClassDef):
                        visit(child, name + ".")
        visit(tree)
    return sections


def finding_fingerprint(section, group) -> str:
    import json
    from .models import digest
    facts = sorted([c.kind, c.unit.id, c.after.contract if c.after else None, c.after.semantic if c.after else None] for c in group)
    return digest(json.dumps([section.id, digest(section.text), facts]))


def load_baseline(text: str | None) -> set[tuple[str, str]]:
    """Parse .docmend-baseline.json into (section_id, fingerprint) pairs."""
    import json
    if not text:
        return set()
    try:
        raw = json.loads(text)
        if raw.get("version") != 1 or not isinstance(raw.get("acknowledged"), list):
            raise ValueError()
        pairs = {(e["section_id"], e["fingerprint"]) for e in raw["acknowledged"]}
        if not all(isinstance(a, str) and isinstance(b, str) for a, b in pairs):
            raise ValueError()
        return pairs
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise DocMendError("Invalid .docmend-baseline.json") from exc


def analyze_files(before: dict[str, str], after: dict[str, str], *, base: str = "fixture-base", head: str = "fixture-head", cfg: Config | None = None, provider: ModelProvider | None = None, semantic: bool = False, embedder=None, budget: Budget | None = None, baseline: set[tuple[str, str]] | None = None) -> tuple[Report, dict]:
    cfg = cfg or Config()
    budget = budget or Budget(cfg.analysis_timeout_seconds)
    budget.remaining()
    old_units, new_units = parse_code(before, review_duplicates=True), parse_code(after, review_duplicates=True)
    budget.remaining()
    old_docs, new_docs = parse_docs(before), parse_docs(after)
    if semantic and embedder is not None:
        from .mapping import CachingEmbedder
        embedder = CachingEmbedder(embedder)
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
        # A renamed unit is documented under its old name, its new name, or both.
        ids = {u.id for u in (change.before, change.after) if u}
        sections = set().union(*(linked[i] for i in ids))
        for sid in sorted(sections):
            if sid in new_docs:
                suspects[sid].append(change)
        if not sections:
            report.warnings.append(f"No documentation mapping for changed unit {change.unit.id}; coverage is incomplete")
    if cfg.docstrings:
        # A docstring documents its own unit. Only signature-level changes
        # flag it; body edits would make every docstring noisy.
        docstrings = docstring_sections(after, new_units)
        for change in changes:
            sid = f"{change.unit.id}#docstring"
            if change.kind in ("contract", "renamed") and sid in docstrings:
                suspects[sid].append(change)
        new_docs = {**new_docs, **docstrings}
    selected = sorted(suspects)
    if len(suspects) > cfg.max_sections:
        # Check the most important sections and say loudly what was skipped,
        # instead of producing nothing. Priority: contract/rename changes
        # (repairable), then removals, then sections with the most changes.
        rank = {"contract": 0, "renamed": 0, "removed": 1, "behaviour": 2, "added": 3}
        selected = sorted(suspects, key=lambda sid: (min(rank.get(c.kind, 4) for c in suspects[sid]), -len(suspects[sid]), sid))[:cfg.max_sections]
        skipped = sorted(set(suspects) - set(selected))
        report.incomplete = True
        report.warnings.append(f"Incomplete analysis: {len(skipped)} of {len(suspects)} linked sections were not checked because max_sections is {cfg.max_sections}; first skipped: {', '.join(skipped[:10])}")
        selected = sorted(selected)
    names = Counter(u.name.rsplit(".", 1)[-1] for u in new_units.values())
    for sid in selected:
        budget.remaining()
        group = suspects[sid]
        ambiguous = any(names[c.unit.name.rsplit(".", 1)[-1]] > 1 for c in group)
        finding, edit = diagnose(new_docs[sid], group, ambiguous=ambiguous, provider=provider, min_confidence=cfg.min_stale_confidence, require_agreement=cfg.require_agreement)
        if edit and sid.endswith("#docstring"):
            # Repairs are Markdown-only; report the docstring, never edit code.
            finding.reason += "; docstring repairs are not generated, update it by hand"
            edit = None
        if edit:
            try:
                validate_edit(edit)
            except DocMendError as exc:
                finding.status = "review"
                finding.reason += f"; correction rejected: {exc}"
                edit = None
        finding.fingerprint = finding_fingerprint(new_docs[sid], group)
        # Only review findings can be acknowledged; confirmed drift never is.
        finding.acknowledged = finding.status == "review" and (sid, finding.fingerprint) in (baseline or set())
        report.findings.append(finding)
        if edit:
            report.edits.append(edit)
    # Coverage cannot be inferred from the number of mapped suspects alone.
    if not provider:
        report.warnings.append("Offline mode: behavioural and ambiguous changes are review findings, not LLM-verified decisions")
    budget.remaining()
    from dataclasses import asdict as _asdict
    from urllib.parse import urlsplit
    from . import __version__
    import json as _json
    from .models import digest
    report.provenance = {
        "tool": "docmend", "version": __version__,
        "config_sha256": digest(_json.dumps(_asdict(cfg), sort_keys=True, default=list)),
        "mode": "llm" if provider else "offline", "semantic_mapping": bool(semantic and embedder),
        "provider_host": urlsplit(cfg.endpoint).hostname if (provider or (semantic and embedder)) and cfg.endpoint else None,
        "model": cfg.model if provider else None,
        "embedding_model": cfg.embedding_model if semantic and embedder else None,
        "model_exchanges": list(getattr(provider, "exchanges", [])),
    }
    new_index["operations"] = {"elapsed_ms": budget.elapsed_ms(), "provider_requests": getattr(provider or getattr(embedder, "inner", embedder), "request_count", 0), "embedded_texts": getattr(embedder, "texts_sent", 0), "runtime_limit_seconds": cfg.analysis_timeout_seconds, "provider_request_limit": cfg.max_provider_requests}
    return report, new_index


def analyze_repository(store: GitStore, base_ref: str, head_ref: str, *, cfg: Config | None = None, llm: bool = False, semantic: bool = False) -> tuple[Report, dict, dict[str, str]]:
    store.budget = None  # A reused store starts a fresh analysis budget.
    base = store.resolve(base_ref)
    # "STAGED" checks the index (what the next commit would contain), for
    # pre-commit hooks. Its report is for checking only, not for apply.
    head = store.staged_tree() if head_ref == "STAGED" else store.resolve(head_ref)
    # Read config from immutable base, not the untrusted PR working tree.
    cfg = cfg or store.trusted_config(base)
    budget = Budget(cfg.analysis_timeout_seconds)
    store.budget = budget
    provider = ModelProvider(cfg, budget=budget) if llm or semantic else None
    before, after = store.snapshot(base, cfg), store.snapshot(head, cfg)
    # Like config, the baseline comes from the trusted base commit, so a PR
    # cannot acknowledge its own review findings.
    try:
        baseline_text = store.run("show", f"{base}:.docmend-baseline.json").decode()
    except DocMendError:
        baseline_text = None
    report, index = analyze_files(before, after, base=base, head=head, cfg=cfg, provider=provider if llm else None, semantic=semantic, embedder=provider, budget=budget, baseline=load_baseline(baseline_text))
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
