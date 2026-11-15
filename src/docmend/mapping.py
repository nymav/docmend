"""Explicit code references plus optional real embedding similarity; no synthetic vectors."""
import math
import re
from dataclasses import asdict
from typing import Protocol

from .models import CodeUnit, DocMendError, Section, digest


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right) or any(not math.isfinite(v) for v in left + right):
        raise DocMendError("Invalid embedding dimensions or values")
    norm = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
    return sum(a*b for a, b in zip(left, right)) / norm if norm else 0.0


# Short or everyday symbol names appear in ordinary prose ("run the tests",
# "the name field"). They only link when written as code or fully qualified.
COMMON_WORDS = frozenset("""add app apply base build call check client close config create data debug default
delete error execute file get handler help host id index info init items key list load main model name open
parse path port process read reset result run save send server set start status stop test type update url
user value version view write""".split())


def weak_name(name: str) -> bool:
    return len(name) <= 3 or name.lower() in COMMON_WORDS


def _code_spans(text: str) -> str:
    return "\n".join(re.findall(r"`([^`\r\n]+)`", text))


def _words(key: str, text: str, cache: dict | None) -> frozenset:
    if cache is None:
        return frozenset(re.findall(r"\w+", text))
    if key not in cache:
        cache[key] = frozenset(re.findall(r"\w+", text))
    return cache[key]


def _mentions(name: str, key: str, text: str, cache: dict | None) -> bool:
    # A plain word name matches exactly when it is one of the text's \w+
    # tokens, which is what the boundary regex checks; skip the scan.
    if re.fullmatch(r"\w+", name):
        return name in _words(key, text, cache)
    return re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text) is not None


def explicit(section: Section, unit: CodeUnit, cache: dict | None = None) -> bool:
    short = unit.name.rsplit(".", 1)[-1]
    prose = [unit.name] if unit.name != short else []
    # A dotted/qualified name is specific enough anywhere; a weak short name
    # must appear inside inline code.
    code_only = [short] if weak_name(short) else []
    if not weak_name(short):
        prose.append(short)
    if unit.kind == "function":
        prose += unit.facts.get("cli_names", [])
        prose += [m for decorator in unit.facts.get("decorators", []) for m in re.findall(r"['\"](/[^'\"]+)['\"]", decorator)]
    if any(_mentions(n, section.id, section.text, cache) for n in prose):
        return True
    return bool(code_only) and any(_mentions(n, section.id + "\0code", _code_spans(section.text), cache) for n in code_only)


def build_index(units: dict[str, CodeUnit], sections: dict[str, Section], *, embedder: Embedder | None = None, threshold: float = .78) -> dict:
    links = []
    unit_list, section_list = list(units.values()), list(sections.values())
    vectors = None
    if embedder and unit_list and section_list:
        vectors = embedder.embed([u.source for u in unit_list] + [s.text for s in section_list])
        if len(vectors) != len(unit_list) + len(section_list):
            raise DocMendError("Embedding response count mismatch")
    cache: dict = {}
    for j, section in enumerate(section_list):
        for i, unit in enumerate(unit_list):
            if explicit(section, unit, cache):
                links.append({"unit": unit.id, "section": section.id, "method": "reference", "score": 1.0})
            elif vectors:
                score = cosine(vectors[i], vectors[len(unit_list)+j])
                if score >= threshold:
                    links.append({"unit": unit.id, "section": section.id, "method": "embedding", "score": score})
    graph = {"schema_version": 1, "units": [asdict(u) for u in unit_list], "sections": [asdict(s) for s in section_list], "links": links}
    import json
    graph["fingerprint"] = digest(json.dumps(graph, sort_keys=True))
    return graph
