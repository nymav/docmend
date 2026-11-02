"""Non-overlapping Markdown sections with stable heading paths and exact source spans."""
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


def parse_docs(files: dict[str, str]) -> dict[str, Section]:
    sections = {}
    for path, text in sorted(files.items()):
        if not path.endswith((".md", ".mdx")):
            continue
        lines = text.splitlines(keepends=True)
        hs = headings(text)
        boundaries = [(0, "Preamble"), *hs] if not hs or hs[0][0] else hs
        stack: list[tuple[int, str]] = []
        seen: Counter = Counter()
        for j, (start, title) in enumerate(boundaries):
            end = boundaries[j+1][0] if j+1 < len(boundaries) else len(lines)
            if end <= start:
                continue
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
