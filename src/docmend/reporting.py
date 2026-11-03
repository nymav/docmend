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
    return {"changed_units": len(report.changes), "stale": sum(f.status == "stale" for f in report.findings), "review": sum(f.status == "review" for f in report.findings), "accurate": sum(f.status == "accurate" for f in report.findings), "safe_edits": sum(e.mode == "safe" for e in report.edits), "draft_edits": sum(e.mode == "draft" for e in report.edits), "coverage_gaps": sum("No documentation mapping" in w for w in report.warnings)}


def markdown(report: Report) -> str:
    counts = summary(report)
    lines = ["<!-- docmend-summary:v1 -->", "## DocMend documentation check", "", f"Base `{report.base}` · Head `{report.head}`", "", " | ".join(f"**{k.replace('_',' ')}:** {v}" for k, v in counts.items()), "", "| Document section | Status | Evidence | Diagnosis |", "|---|---|---|---|"]
    for finding in report.findings:
        lines.append(f"| {cell(finding.path)}: {cell(finding.heading)} | {cell(finding.status)} | {cell(finding.evidence)} | {cell(finding.reason)} |")
    if not report.findings:
        lines += ["", "No mapped documentation drift was identified. This is not a claim of complete documentation accuracy."]
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
