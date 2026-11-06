"""Conservative, explainable drift checks; model judgments never auto-approve edits."""
from __future__ import annotations

import ast
import re
from typing import Any

from .models import Change, DocMendError, Edit, Finding, Section
from .provider import ModelProvider


def _inline(text: str):
    # Ignore fenced code blocks and code spans containing newlines.
    fence = None
    offset = 0
    hidden = [(m.start(), m.end()) for m in re.finditer(r"<!--.*?(?:-->|$)", text, re.S)]
    for line in text.splitlines(keepends=True):
        f = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if f:
            if fence is None:
                fence = f[1]
            elif f[1][0] == fence[0] and len(f[1]) >= len(fence):
                fence = None
        elif fence is None:
            for m in re.finditer(r"(?<!`)`([^`\r\n]+)`(?!`)", line):
                start, end = offset + m.start(1), offset + m.end(1)
                if not any(left < end and start < right for left, right in hidden):
                    yield start, end, m[1]
        offset += len(line)


def _declared_fact(text: str, offset: int, heading: str = "") -> bool:
    # An explicit argument in an example may intentionally override the default.
    # Automatic repair needs a declaration label, not just a matching old number.
    line = text[text.rfind("\n", 0, offset) + 1:offset].rstrip("`").strip()
    if re.search(r"\b(?:old|previous|former|formerly|historical|deprecated|obsolete|legacy|example|override)\b", line, re.I):
        return False
    if re.search(r"\b(?:history|changelog|archive|deprecated|migration)\b", heading, re.I):
        return False
    return bool(re.search(r"(?:signature|default(?: value)?|default configuration)\s*(?:is\s*)?:?\s*$", line, re.I))


def _static_rewrite(section: Section, change: Change) -> tuple[str, str] | None:
    old, new = change.before, change.after
    if change.kind != "contract" or old is None or new is None or old.kind != new.kind:
        return None
    replacements = []
    reasons = []
    for start, end, snippet in _inline(section.text):
        if not _declared_fact(section.text, start, section.heading):
            continue
        result = snippet
        if old.kind == "function":
            # Only rewrite exact documented signatures, or literal old defaults in
            # a call to this specific function. Narrative paraphrases stay review-only.
            if snippet == old.facts["signature"]:
                result = new.facts["signature"]
            elif re.match(r"^" + re.escape(old.name.rsplit(".", 1)[-1]) + r"\(", snippet):
                try:
                    call = ast.parse(snippet, mode="eval").body
                except SyntaxError:
                    continue
                if not isinstance(call, ast.Call):
                    continue
                before_params, after_params = old.facts["params"], new.facts["params"]
                # A renamed/removed parameter is not a literal-default edit.
                if set(before_params) != set(after_params):
                    continue
                for key, previous in before_params.items():
                    current = after_params[key]
                    if previous is None or current is None or previous == current:
                        continue
                    result = re.sub(r"(?<!\w)(" + re.escape(key) + r"\s*=\s*)" + re.escape(previous) + r"(?=\s*[,\)])", lambda m: m[1] + current, result)
            if result != snippet:
                reasons.append("Documented call/default differs from the new AST contract")
        elif old.kind == "config":
            previous, current = old.facts.get("value"), new.facts.get("value")
            if previous is not None and current is not None:
                pattern = re.escape(old.name) + r"\s*=\s*" + re.escape(previous)
                if re.fullmatch(pattern, snippet):
                    result = old.name + "=" + current
                    reasons.append("Explicit documented config literal differs from the new value")
        if result != snippet:
            replacements.append((start, end, result))
    if not replacements:
        return None
    updated = section.text
    for start, end, replacement in reversed(replacements):
        updated = updated[:start] + replacement + updated[end:]
    return updated, "; ".join(sorted(set(reasons)))


def context(section: Section, changes: list[Change]) -> dict[str, Any]:
    return {"documentation": section.text, "changes": [{"kind": c.kind, "unit": c.unit.id, "before": c.before.source if c.before else None, "after": c.after.source if c.after else None} for c in changes]}


def diagnose(section: Section, changes: list[Change], *, ambiguous: bool = False, provider: ModelProvider | None = None) -> tuple[Finding, Edit | None]:
    ids = sorted(c.unit.id for c in changes)
    if any(u and u.kind == "ambiguous" for c in changes for u in (c.before, c.after)):
        return Finding(section.id, section.path, section.heading, "review",
            "Repeated definition or member of a repeated class; active binding requires human review and no repair is generated",
            ids), None
    # Multiple changes are evaluated jointly by a model or human, never chained
    # into a misleadingly high-confidence deterministic repair.
    if len(changes) == 1 and not ambiguous and not (changes[0].before and changes[0].after and changes[0].before.kind == "function" and changes[0].before.semantic != changes[0].after.semantic):
        rewrite = _static_rewrite(section, changes[0])
        if rewrite:
            after, reason = rewrite
            return Finding(section.id, section.path, section.heading, "stale", reason, ids, 1.0), Edit(section.id, section.path, section.start, section.end, section.text, after, section.file_hash, "safe", reason)
        old, new = changes[0].before, changes[0].after
        if old and new and old.kind == new.kind:
            snippets = [value for start, _, value in _inline(section.text) if _declared_fact(section.text, start, section.heading)]
            current = False
            if old.kind == "function" and old.facts["signature"] != new.facts["signature"]:
                current = new.facts["signature"] in snippets
            elif old.kind == "config" and old.facts.get("value") != new.facts.get("value"):
                current = any(re.fullmatch(re.escape(new.name) + r"\s*=\s*" + re.escape(str(new.facts["value"])), value) for value in snippets)
            if current:
                return Finding(section.id, section.path, section.heading, "accurate", "Explicit documented signature/config literal matches the new contract; surrounding prose is not semantically certified", ids, 1.0), None
    if provider:
        answer = provider.json('Return {"status":"stale"|"accurate"|"uncertain","reason":string,"confidence":number}. Confidence is a self-rating, not a calibrated probability.', context(section, changes))
        if set(answer) != {"status", "reason", "confidence"} or answer["status"] not in ("stale", "accurate", "uncertain") or not isinstance(answer["reason"], str) or len(answer["reason"]) > 4000 or type(answer["confidence"]) not in (int, float) or not 0 <= answer["confidence"] <= 1:
            raise DocMendError("Model diagnosis does not match the response contract")
        status = "review" if answer["status"] == "uncertain" else answer["status"]
        finding = Finding(section.id, section.path, section.heading, status, answer["reason"], ids, float(answer["confidence"]), "model")
        if status != "stale":
            return finding, None
        draft = provider.json('Return {"after":string,"reason":string}. Rewrite only the supplied documentation section, preserving heading lines, code fences, links and accurate material. Do not invent APIs or features. Include TODO(DocMend) only if a substantive ambiguity needs author review.', {**context(section, changes), "diagnosis": answer["reason"]})
        if set(draft) != {"after", "reason"} or not all(isinstance(draft[k], str) for k in draft) or not draft["after"] or len(draft["after"]) > max(1000, len(section.text)*2):
            raise DocMendError("Model repair does not match the response contract")
        critic = provider.json('Return {"accurate":boolean,"preserves_unaffected":boolean,"reason":string}. Audit the proposed correction against supplied code and original documentation. Reject unsupported claims or unrelated rewrites.', {**context(section, changes), "proposed_documentation": draft["after"]})
        if set(critic) != {"accurate", "preserves_unaffected", "reason"} or type(critic["accurate"]) is not bool or type(critic["preserves_unaffected"]) is not bool or not isinstance(critic["reason"], str):
            raise DocMendError("Repair validation does not match the response contract")
        if not critic["accurate"] or not critic["preserves_unaffected"]:
            finding.status = "review"
            finding.reason += "; repair validator rejected the draft"
            return finding, None
        return finding, Edit(section.id, section.path, section.start, section.end, section.text, draft["after"], section.file_hash, "draft", draft["reason"], "model")
    reason = "Changed code is linked to this section; semantic accuracy requires review"
    if ambiguous:
        reason += "; the short symbol name is ambiguous across source units"
    if any(c.kind in ("added", "removed") for c in changes):
        reason += "; feature addition/removal is not auto-rewritten"
    return Finding(section.id, section.path, section.heading, "review", reason, ids), None
