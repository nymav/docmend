"""Non-overlapping Markdown and reStructuredText sections with stable heading paths and exact source spans."""
import re
import unicodedata
from collections import Counter

from .models import Section, digest


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^\w-]+", "-", text).strip("-") or "section"


def headings(text: str) -> list[tuple[int, str]]:
    result = []
    fence = None
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        f = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if f:
            mark = f[1]
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence) and not line[f.end():].strip():
                fence = None
            continue
        if fence:
            continue
        m = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line.rstrip("\r\n"))
        if m:
            result.append((i, m[2].strip()))
        elif i and re.fullmatch(r" {0,3}(?:=+|-+)\s*", line.rstrip("\r\n")) and lines[i-1].strip():
            result.append((i-1, lines[i-1].strip()))
    return result


DOC_SUFFIXES = (".md", ".mdx", ".rst")
_ADORN = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"


def _rule(line: str) -> str | None:
    """Return the adornment character when the line is a reST section rule."""
    s = line.rstrip("\r\n")
    if len(s) >= 2 and s[0] in _ADORN and s == s[0] * len(s):
        return s[0]
    return None


def literal_lines(text: str) -> set[int]:
    """Line numbers inside reST literal blocks (after ``::`` or a directive)."""
    lines = text.splitlines()
    hidden, i = set(), 0
    while i < len(lines):
        line = lines[i]
        opens = line.rstrip().endswith("::") or re.match(r"^\s*\.\.\s", line)
        if opens:
            indent = len(line) - len(line.lstrip())
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent):
                if lines[j].strip():
                    hidden.add(j)
                j += 1
            i = j
            continue
        i += 1
    return hidden


def rst_headings(text: str) -> list[tuple[int, str, int]]:
    """(first line, title, level). Levels follow the order styles first appear."""
    styles: list[tuple[str, bool]] = []
    result = []
    for start, title, style in rst_heading_styles(text):
        if style not in styles:
            styles.append(style)
        result.append((start, title, styles.index(style) + 1))
    return result


def rst_heading_styles(text: str) -> list[tuple[int, str, tuple[str, bool]]]:
    """(first line, title, (adornment character, has overline))."""
    lines = text.splitlines()
    hidden = literal_lines(text)
    result = []
    i = 0
    while i < len(lines):
        if i in hidden:
            i += 1
            continue
        over = _rule(lines[i])
        title = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if over and title and i + 2 < len(lines) and _rule(lines[i + 2]) == over and not _rule(lines[i + 1]):
            style, start, nxt = (over, True), i, i + 3
        elif lines[i].strip() and not lines[i][0].isspace() and not _rule(lines[i]) and i + 1 < len(lines) \
                and _rule(lines[i + 1]) and len(lines[i + 1].rstrip()) >= len(lines[i].rstrip()) \
                and (i == 0 or not lines[i - 1].strip() or _rule(lines[i - 1])):
            style, start, title, nxt = (_rule(lines[i + 1]), False), i, lines[i].strip(), i + 2
        else:
            i += 1
            continue
        result.append((start, title, style))
        i = nxt
    return result


def parse_docs(files: dict[str, str]) -> dict[str, Section]:
    sections = {}
    for path, text in sorted(files.items()):
        if not path.endswith(DOC_SUFFIXES):
            continue
        lines = text.splitlines(keepends=True)
        if path.endswith(".rst"):
            levels = {start: level for start, _, level in rst_headings(text)}
            hs = [(start, title) for start, title, _ in rst_headings(text)]
        else:
            levels = None
            hs = headings(text)
        boundaries = [(0, "Preamble"), *hs] if not hs or hs[0][0] else hs
        stack: list[tuple[int, str]] = []
        seen: Counter = Counter()
        for j, (start, title) in enumerate(boundaries):
            end = boundaries[j+1][0] if j+1 < len(boundaries) else len(lines)
            if end <= start:
                continue
            if levels is not None:
                level = levels.get(start, 1)
            else:
                level = len(re.match(r"^\s*(#+)", lines[start])[1]) if re.match(r"^\s*(#+)", lines[start]) else 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            name = " > ".join(t for _, t in stack)
            key = slug(name)
            seen[key] += 1
            suffix = f"-{seen[key]}" if seen[key] > 1 else ""
            sid = f"{path}#{key}{suffix}"
            sections[sid] = Section(sid, path, name, start, end, "".join(lines[start:end]), digest(text))
    return sections
