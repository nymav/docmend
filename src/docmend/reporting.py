"""Portable JSON, Markdown and patch artifacts; no HTML or terminal injection."""
from __future__ import annotations

import difflib
import json
from pathlib import Path
import re

from .models import Report
from .sarif import sarif
from .repair import atomic_write, patched_files, safe_path


def cell(text: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(text)).replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;").replace("`", "'")


def summary(report: Report) -> dict:
    return {"changed_units": len(report.changes), "stale": sum(f.status == "stale" for f in report.findings), "review": sum(f.status == "review" and not f.acknowledged for f in report.findings), "acknowledged": sum(f.acknowledged for f in report.findings), "accurate": sum(f.status == "accurate" for f in report.findings), "safe_edits": sum(e.mode == "safe" for e in report.edits), "draft_edits": sum(e.mode == "draft" for e in report.edits), "coverage_gaps": sum("No documentation mapping" in w for w in report.warnings), "incomplete": int(report.incomplete)}


MAX_CARDS = 40


def _fence(text: str) -> str:
    # Inline HTML does not stop Markdown parsing, so every character that
    # Markdown or HTML treats specially becomes an entity.
    raw = re.sub(r"[\x00-\x1f\x7f]", " ", str(text))[:300]
    safe = "".join(f"&#{ord(ch)};" if ch in "&<>\"'`|*_[]\\~#!$" else ch for ch in raw)
    return "<code>" + safe + "</code>"


def evidence_section(report: Report) -> list[str]:
    """Collapsible evidence card per stale/review finding, capped for PR comments."""
    from .models import REASON_CODES
    shown = [f for f in report.findings if f.status in ("stale", "review") and f.card]
    if not shown:
        return []
    out = ["", "### Evidence", ""]
    for f in shown[:MAX_CARDS]:
        c = f.card
        outcome = f.codes[0] if f.codes else ""
        out += [f"<details><summary>{cell(f.path)}: {cell(f.heading)} — <code>{cell(outcome)}</code></summary>", ""]
        out.append(f"- **Rule:** {cell(REASON_CODES.get(outcome, f.reason))}")
        d = c.get("doc", {})
        out.append(f"- **Doc:** {_fence(d.get('path', ''))} lines {d.get('lines', ['?', '?'])[0]}–{d.get('lines', ['?', '?'])[1]} at head {_fence(report.head[:12])}")
        for fact in c.get("declared_facts", [])[:5]:
            out.append(f"  - line {fact['line']} declares {_fence(fact['text'])}")
        if not c.get("declared_facts"):
            out.append("  - no declared Signature/Default fact in this section")
        for ch in c.get("changes", []):
            out.append(f"- **Code change:** {_fence(ch['unit'])} ({cell(ch['change'])})")
            for side, commit in (("before", report.base), ("after", report.head)):
                u = ch.get(side)
                if u:
                    out.append(f"  - {side} {_fence(commit[:12])} {_fence(u['path'])} lines {u['lines'][0]}–{u['lines'][1]}: {_fence(u['states'])}")
                else:
                    out.append(f"  - {side}: does not exist")
        e = c.get("edit")
        if e:
            out.append(f"- **{e['mode'].title()} edit:** " + "; ".join(_fence(x) for x in e["removed"]) + " → " + "; ".join(_fence(x) for x in e["added"]))
        out += ["", "</details>"]
    if len(shown) > MAX_CARDS:
        out += ["", f"{len(shown) - MAX_CARDS} more evidence cards are in report.json."]
    return out


def markdown(report: Report) -> str:
    counts = summary(report)
    lines = ["<!-- docmend-summary:v1 -->", "## DocMend documentation check", "", *(["> **Incomplete analysis.** Some linked sections were not checked; see Analysis limits.", ""] if report.incomplete else []), f"Base `{report.base}` · Head `{report.head}`", "", " | ".join(f"**{k.replace('_',' ')}:** {v}" for k, v in counts.items()), "", "| Document section | Status | Evidence | Diagnosis | Codes |", "|---|---|---|---|---|"]
    for finding in report.findings:
        lines.append(f"| {cell(finding.path)}: {cell(finding.heading)} | {cell(finding.status + (' (acknowledged)' if finding.acknowledged else ''))} | {cell(finding.evidence)} | {cell(finding.reason)} | {cell(' '.join(finding.codes))} |")
    if not report.findings:
        lines += ["", "No mapped documentation drift was identified. This is not a claim of complete documentation accuracy."]
    lines += evidence_section(report)
    if report.warnings:
        lines += ["", "### Analysis limits", "", *["- " + cell(w) for w in report.warnings]]
    lines += ["", "Safe edits are limited to explicit documented signatures/defaults/config literals. Model judgments and drafts require review. Confidence is not a calibrated correctness probability.", ""]
    return "\n".join(lines)


def unified_patch(files: dict[str, str], report: Report, *, drafts: bool = False) -> str:
    updated = patched_files(files, report.edits, include_drafts=drafts)
    chunks = []
    for path, after in sorted(updated.items()):
        chunks.extend(difflib.unified_diff(files[path].splitlines(keepends=True), after.splitlines(keepends=True), fromfile="a/" + path, tofile="b/" + path))
    return "".join(chunks)


def save(root: Path, directory: str, report: Report, index: dict, files: dict[str, str]) -> None:
    output = safe_path(root, directory)
    # Ensure existing children are not symlinks before any writes.
    targets = {name: safe_path(root, str(Path(directory) / name)) for name in ["report.sarif", "report.json", "summary.md", "index.json", "safe.patch", "draft.patch"]}
    output.mkdir(parents=True, exist_ok=True)
    values = {"report.sarif": json.dumps(sarif(report, index.get("sections", [])), indent=2) + "\n", "report.json": report.to_json(), "summary.md": markdown(report), "index.json": json.dumps(index, indent=2, ensure_ascii=False) + "\n", "safe.patch": unified_patch(files, report), "draft.patch": unified_patch(files, report, drafts=True)}
    for name, text in values.items():
        atomic_write(targets[name], text)
