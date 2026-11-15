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


_NOT_LITERAL = object()


def _literal_value(text: str):
    try:
        return ast.literal_eval(text.strip())
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return _NOT_LITERAL


def _same_value(doc: str, code: str) -> bool:
    """True when two literals mean the same value: 1e-6 == 1e-06, 'a' == "a"."""
    a, b = _literal_value(doc), _literal_value(code)
    if a is _NOT_LITERAL or b is _NOT_LITERAL:
        return doc.strip() == code.strip()
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        return type(a) is type(b) and a == b  # True must not equal 1
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def _in_doc_style(code: str, doc: str) -> str:
    """Write the new code literal the way the doc wrote the old one."""
    old, new = _literal_value(doc), _literal_value(code)
    written = doc.strip()
    if isinstance(new, str) and isinstance(old, str):
        raw = written[:1] in "rR" and written[1:2] in "'\""
        quote = written[1:2] if raw else written[:1]
        if quote in "'\"" and quote and quote not in new and "\n" not in new and "\r" not in new:
            if raw and not new.endswith("\\"):
                return written[0] + quote + new + quote
            if not raw and "\\" not in new:
                return quote + new + quote
    if isinstance(new, float) and isinstance(old, float) and "e" in doc.lower() and "e" in code.lower():
        return re.sub(r"e([+-]?)0+(\d)", r"e\1\2", code)  # 1e-09 -> 1e-9 like the doc
    return code


def _normal_signature(snippet: str) -> str | None:
    """Canonical `name(args)` for a documented signature, ignoring spacing/quotes."""
    m = re.fullmatch(r"\s*(\w+)\s*(\(.*\))\s*", snippet, re.S)
    if not m:
        return None
    try:
        fn = ast.parse(f"def {m[1]}{m[2]}: pass").body[0]
    except (SyntaxError, ValueError, RecursionError):
        return None
    return fn.name + "(" + ast.unparse(fn.args) + ")"


def _restyle_defaults(snippet: str, before: dict, after: dict) -> str | None:
    """Swap old default values written in a call/signature, keeping the doc's spelling."""
    try:
        call = ast.parse(snippet, mode="eval").body
    except SyntaxError:
        try:
            fn = ast.parse(f"def {snippet}: pass").body[0]
        except SyntaxError:
            return None
        args = fn.args.posonlyargs + fn.args.args
        pairs = list(zip([a.arg for a in args[len(args) - len(fn.args.defaults):]], fn.args.defaults))
        pairs += [(a.arg, d) for a, d in zip(fn.args.kwonlyargs, fn.args.kw_defaults) if d is not None]
        shift = len("def ")
    else:
        if not isinstance(call, ast.Call):
            return None
        pairs = [(k.arg, k.value) for k in call.keywords if k.arg]
        shift = 0
    if set(before) != set(after):
        return None  # A renamed/removed parameter is not a literal-default edit.
    spans = []
    for name, node in pairs:
        previous, current = before.get(name), after.get(name)
        if previous is None or current is None or _same_value(previous, current):
            continue
        a, b = node.col_offset - shift, node.end_col_offset - shift
        written = snippet[a:b]
        if _same_value(written, previous):
            spans.append((a, b, _in_doc_style(current, written)))
    result = snippet
    for a, b, text in sorted(spans, reverse=True):
        result = result[:a] + text + result[b:]
    return result if spans else None


_HISTORY = r"\b(?:old|previous|former|formerly|historical|deprecated|obsolete|legacy|example|examples|override|e\.g\.)\b"


def _fenced_facts(text: str, heading: str = ""):
    """Single-line statements inside a Python code block that the doc declares as defaults.

    The block must be ```python/```py and introduced by a line ending in
    "Signature:", "Default(s):" or "Default configuration:". Lines with a
    comment are skipped: comments usually say "override" or "example".
    """
    if re.search(r"\b(?:history|changelog|archive|deprecated|migration)\b", heading, re.I):
        return
    lines = text.splitlines(keepends=True)
    offset, fence, declared, prose = 0, None, False, ""
    for line in lines:
        f = re.match(r"^ {0,3}(`{3,}|~{3,})\s*([\w+-]*)", line)
        if fence is None and f:
            fence = f[1]
            declared = f[2].lower() in ("python", "py", "python3") and not re.search(_HISTORY, prose, re.I) \
                and bool(re.search(r"(?:signature|defaults?(?: values?)?|default configuration)\s*(?:are|is)?\s*:\s*$", prose, re.I))
        elif fence is not None and f and f[1][0] == fence[0] and len(f[1]) >= len(fence) and not line[f.end():].strip():
            fence, declared = None, False
        elif fence is not None:
            body = line.rstrip("\r\n")
            if declared and body.strip() and "#" not in body:
                lead = len(body) - len(body.lstrip())
                yield offset + lead, offset + len(body), body.strip()
        elif line.strip():
            prose = line.strip()
        offset += len(line)


def _facts(text: str, heading: str, rst: bool = False):
    """Every declared fact: labelled inline code plus labelled Python block lines."""
    found = [(a, b, v) for a, b, v in _inline(text, rst) if _declared_fact(text, a, heading)]
    if not rst:
        found += list(_fenced_facts(text, heading))
    return sorted(found)


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
        m = re.fullmatch(re.escape(name) + separators + r"(.+?)\s*", snippet, re.S)
        if not m:
            continue
        written = m[2]
        for form, unquoted in forms:
            if (written == form) if unquoted else _same_value(written, form):
                return name, m[1], unquoted, written
    return None


def _static_rewrite(section: Section, change: Change) -> tuple[str, str] | None:
    old, new = change.before, change.after
    if change.kind not in ("contract", "renamed") or old is None or new is None or old.kind != new.kind:
        return None
    replacements = []
    reasons = []
    for start, end, snippet in _facts(section.text, section.heading, section.path.endswith('.rst')):
        result = snippet
        if old.kind == "function":
            # Only rewrite exact documented signatures, or literal old defaults in
            # a call to this specific function. Narrative paraphrases stay review-only.
            is_signature = snippet == old.facts["signature"] or _normal_signature(snippet) == _normal_signature(old.facts["signature"])
            if change.kind == "renamed" and not is_signature:
                continue  # Renames only rewrite an exact documented signature.
            styled = None
            if change.kind != "renamed" and not old.facts.get("language") and "\n" not in snippet \
                    and re.match(r"^" + re.escape(old.name.rsplit(".", 1)[-1]) + r"\(", snippet):
                styled = _restyle_defaults(snippet, old.facts["params"], new.facts["params"])
            if is_signature:
                # Prefer the doc's own spelling when only default values moved;
                # otherwise (params added/removed/renamed) write the new signature.
                same_shape = styled is not None and _normal_signature(styled) == _normal_signature(new.facts["signature"])
                result = styled if same_shape else new.facts["signature"]
            elif styled is not None:
                result = styled
            if result != snippet:
                reasons.append("Documented call/default differs from the new AST contract")
        elif old.kind == "config":
            previous, current = old.facts.get("value"), new.facts.get("value")
            if previous is not None and current is not None:
                match = _config_match(old, previous, snippet, section.text)
                replacement = None
                if match:
                    replacement = _unquote(current) if match[2] else _in_doc_style(current, match[3])
                if match and replacement is not None and not _same_value(previous, current):
                    name, separator = match[0], match[1]
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
    snippets = [v for _, _, v in _facts(updated, section.heading, section.path.endswith('.rst'))]
    if old.kind == "function":
        for snippet in snippets:
            if snippet == new.facts["signature"] or _normal_signature(snippet) == _normal_signature(new.facts["signature"]):
                return True
            if re.match(r"^" + re.escape(new.name.rsplit(".", 1)[-1]) + r"\(", snippet):
                try:
                    call = ast.parse(snippet, mode="eval").body
                except SyntaxError:
                    return False
                values = {k.arg: ast.unparse(k.value) for k in getattr(call, "keywords", []) if k.arg}
                changed = {k for k, v in new.facts["params"].items() if v is not None and old.facts["params"].get(k) is not None and not _same_value(old.facts["params"][k], v) and k in values}
                if changed and all(_same_value(values[k], new.facts["params"][k]) for k in changed):
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
            snippets = [value for _, _, value in _facts(section.text, section.heading, section.path.endswith('.rst'))]
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
