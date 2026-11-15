"""Conservative, explainable drift checks; model judgments never auto-approve edits."""
from __future__ import annotations

import ast
import re
from typing import Any

from .models import Change, DocMendError, Edit, Finding, Section
from .provider import ModelProvider


def _inline_rst(text: str):
    # reST inline literals are ``double backticks``; literal blocks are skipped.
    from .docparse import literal_lines
    hidden = literal_lines(text)
    offset = 0
    for i, line in enumerate(text.splitlines(keepends=True)):
        if i not in hidden and not re.match(r"^\s*\.\.\s", line):
            for m in re.finditer(r"``([^`\r\n]+)``", line):
                yield offset + m.start(1), offset + m.end(1), m[1]
        offset += len(line)


def _inline(text: str, rst: bool = False):
    # Ignore fenced code blocks and code spans containing newlines.
    if rst:
        yield from _inline_rst(text)
        return
    fence = None
    offset = 0
    hidden = [(m.start(), m.end()) for m in re.finditer(r"<!--.*?(?:-->|$)", text, re.S)]
    for line in text.splitlines(keepends=True):
        f = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if f:
            if fence is None:
                fence = f[1]
            elif f[1][0] == fence[0] and len(f[1]) >= len(fence) and not line[f.end():].strip():
                # Same closing rule as docparse.headings: no trailing text.
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


def _unquote(value: str) -> str | None:
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    return parsed if isinstance(parsed, str) and re.fullmatch(r"[\w.:/-]+", parsed) else None


def _config_match(unit, value: str, snippet: str, text: str):
    """Match a documented `NAME=value`; returns (name, separator, unquoted) or None.

    CLI flags also match `--flag value`. A dataclass field also matches by its
    short name when the section names its class. A quoted string default also
    matches without quotes (`--mode=fast` for default 'fast').
    """
    names = [unit.name]
    owner = unit.facts.get("owner")
    if owner and re.search(r"(?<!\w)" + re.escape(owner) + r"(?!\w)", text):
        names.append(unit.name.rsplit(".", 1)[-1])
    forms = [(value, False)]
    bare = _unquote(value)
    if bare is not None:
        forms.append((bare, True))
    for name in names:
        separators = r"(\s*=\s*|\s+)" if name.startswith("-") else r"(\s*=\s*)"
        for form, unquoted in forms:
            m = re.fullmatch(re.escape(name) + separators + re.escape(form), snippet)
            if m:
                return name, m[1], unquoted
    return None


def _static_rewrite(section: Section, change: Change) -> tuple[str, str] | None:
    old, new = change.before, change.after
    if change.kind not in ("contract", "renamed") or old is None or new is None or old.kind != new.kind:
        return None
    replacements = []
    reasons = []
    for start, end, snippet in _inline(section.text, section.path.endswith('.rst')):
        if not _declared_fact(section.text, start, section.heading):
            continue
        result = snippet
        if old.kind == "function":
            # Only rewrite exact documented signatures, or literal old defaults in
            # a call to this specific function. Narrative paraphrases stay review-only.
            if snippet == old.facts["signature"]:
                result = new.facts["signature"]
            elif change.kind == "renamed":
                continue  # Renames only rewrite an exact documented signature.
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
                match = _config_match(old, previous, snippet, section.text)
                replacement = current
                if match and match[2]:
                    replacement = _unquote(current)  # keep the documented unquoted style
                if match and replacement is not None:
                    name, separator, _ = match
                    result = name + separator + replacement
                    reasons.append("Explicit documented config literal differs from the new value")
        if result != snippet:
            replacements.append((start, end, result))
    if not replacements:
        return None
    updated = section.text
    for start, end, replacement in reversed(replacements):
        updated = updated[:start] + replacement + updated[end:]
    return updated, "; ".join(sorted(set(reasons)))


def _verify_rewrite(section: Section, updated: str, change: Change) -> bool:
    """Re-read the repaired text and confirm it now states the new contract."""
    from dataclasses import replace
    after = replace(section, text=updated)
    if _static_rewrite(after, change) is not None:
        return False  # Old facts remain after one pass; refuse a partial repair.
    old, new = change.before, change.after
    snippets = [v for start, _, v in _inline(updated, section.path.endswith('.rst')) if _declared_fact(updated, start, section.heading)]
    if old.kind == "function":
        for snippet in snippets:
            if snippet == new.facts["signature"]:
                return True
            if re.match(r"^" + re.escape(new.name.rsplit(".", 1)[-1]) + r"\(", snippet):
                try:
                    call = ast.parse(snippet, mode="eval").body
                except SyntaxError:
                    return False
                values = {k.arg: ast.unparse(k.value) for k in getattr(call, "keywords", []) if k.arg}
                changed = {k for k, v in new.facts["params"].items() if v is not None and old.facts["params"].get(k) != v and k in values}
                if changed and all(values[k] == new.facts["params"][k] for k in changed):
                    return True
        return False
    if old.kind == "config":
        return any(_config_match(new, str(new.facts.get("value")), v, updated) for v in snippets)
    return False

def _draft_problem(section: Section, changes: list[Change], after: str) -> str | None:
    """Deterministic checks a model draft must pass before any critic sees it."""
    import builtins
    import keyword
    before_snippets = [v for _, _, v in _inline(section.text, section.path.endswith('.rst'))]
    after_snippets = [v for _, _, v in _inline(after, section.path.endswith('.rst'))]
    names = {c.unit.name.rsplit(".", 1)[-1] for c in changes}
    # Inline code unrelated to the changed units must survive unchanged.
    for snippet in before_snippets:
        if not any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", snippet) for n in names) and snippet not in after_snippets:
            return f"draft altered unrelated inline code `{snippet}`"
    # New inline code may only use identifiers present in the section or the changed code.
    known = section.text + "\n" + "\n".join(u.source for c in changes for u in (c.before, c.after) if u)
    allowed = set(keyword.kwlist) | set(dir(builtins))
    for snippet in after_snippets:
        if snippet in before_snippets:
            continue
        for token in re.findall(r"[A-Za-z_]\w*", snippet):
            if token not in allowed and not re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", known):
                return f"draft introduced unsupported identifier `{token}`"
    return None


def context(section: Section, changes: list[Change]) -> dict[str, Any]:
    return {"documentation": section.text, "changes": [{"kind": c.kind, "unit": c.unit.id, "before": c.before.source if c.before else None, "after": c.after.source if c.after else None} for c in changes]}


def _valid_diagnosis(answer: dict) -> bool:
    return set(answer) == {"status", "reason", "confidence"} and answer["status"] in ("stale", "accurate", "uncertain") and isinstance(answer["reason"], str) and len(answer["reason"]) <= 4000 and type(answer["confidence"]) in (int, float) and 0 <= answer["confidence"] <= 1


def diagnose(section: Section, changes: list[Change], *, ambiguous: bool = False, provider: ModelProvider | None = None, min_confidence: float = 0.0, require_agreement: bool = False) -> tuple[Finding, Edit | None]:
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
            if not _verify_rewrite(section, after, changes[0]):
                return Finding(section.id, section.path, section.heading, "review", reason + "; repaired text did not re-verify against the new contract, so no repair is offered", ids), None
            return Finding(section.id, section.path, section.heading, "stale", reason, ids, 1.0), Edit(section.id, section.path, section.start, section.end, section.text, after, section.file_hash, "safe", reason)
        old, new = changes[0].before, changes[0].after
        if old and new and old.kind == new.kind:
            snippets = [value for start, _, value in _inline(section.text, section.path.endswith('.rst')) if _declared_fact(section.text, start, section.heading)]
            current = False
            if old.kind == "function" and old.facts["signature"] != new.facts["signature"]:
                current = new.facts["signature"] in snippets
            elif old.kind == "config" and old.facts.get("value") != new.facts.get("value"):
                current = any(_config_match(new, str(new.facts["value"]), value, section.text) for value in snippets)
            if current:
                return Finding(section.id, section.path, section.heading, "accurate", "Explicit documented signature/config literal matches the new contract; surrounding prose is not semantically certified", ids, 1.0), None
    if provider:
        prompt = 'Return {"status":"stale"|"accurate"|"uncertain","reason":string,"confidence":number}. Confidence is a self-rating, not a calibrated probability.'
        answer = provider.json(prompt, context(section, changes))
        if not _valid_diagnosis(answer):
            raise DocMendError("Model diagnosis does not match the response contract")
        status = "review" if answer["status"] == "uncertain" else answer["status"]
        finding = Finding(section.id, section.path, section.heading, status, answer["reason"], ids, float(answer["confidence"]), "model")
        if status == "stale" and answer["confidence"] < min_confidence:
            finding.status = "review"
            finding.reason += f"; self-rated confidence {answer['confidence']:.2f} is below the configured minimum {min_confidence:.2f}"
            return finding, None
        if status == "stale" and require_agreement:
            second = provider.json(prompt, context(section, changes))
            if not _valid_diagnosis(second):
                raise DocMendError("Model diagnosis does not match the response contract")
            if second["status"] != "stale":
                finding.status = "review"
                finding.reason += f"; a second diagnosis disagreed ({second['status']})"
                return finding, None
            finding.confidence = min(float(answer["confidence"]), float(second["confidence"]))
        if status != "stale":
            return finding, None
        draft = provider.json('Return {"after":string,"reason":string}. Rewrite only the supplied documentation section, preserving heading lines, code fences, links and accurate material. Do not invent APIs or features. Include TODO(DocMend) only if a substantive ambiguity needs author review.', {**context(section, changes), "diagnosis": answer["reason"]})
        if set(draft) != {"after", "reason"} or not all(isinstance(draft[k], str) for k in draft) or not draft["after"] or len(draft["after"]) > max(1000, len(section.text)*2):
            raise DocMendError("Model repair does not match the response contract")
        problem = _draft_problem(section, changes, draft["after"])
        if problem:
            finding.status = "review"
            finding.reason += "; " + problem
            return finding, None
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
    for c in changes:
        if c.kind == "renamed":
            reason += f"; {c.before.name} appears to be renamed to {c.after.name} (identical body)"
    if any(c.kind in ("added", "removed") for c in changes):
        reason += "; feature addition/removal is not auto-rewritten"
    return Finding(section.id, section.path, section.heading, "review", reason, ids), None
