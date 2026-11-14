"""Explicit code references plus optional real embedding similarity; no synthetic vectors."""
import math
import re
from dataclasses import asdict
from typing import Protocol

from .models import CodeUnit, DocMendError, Section, digest


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class CachingEmbedder:
    """Embeds each distinct text once per run.

    Base and head snapshots share most code and docs, so without this the
    same text is sent to the provider twice (or more, for duplicates).
    Vectors are keyed by content digest and never written to disk.
    """

    def __init__(self, inner: Embedder):
        self.inner = inner
        self.vectors: dict[str, list[float]] = {}
        self.texts_sent = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        keys = [digest(t) for t in texts]
        missing = list(dict.fromkeys(k for k in keys if k not in self.vectors))
        if missing:
            by_key = dict(zip(keys, texts))
            fresh = self.inner.embed([by_key[k] for k in missing])
            if len(fresh) != len(missing):
                raise DocMendError("Embedding response count mismatch")
            self.vectors.update(zip(missing, fresh))
            self.texts_sent += len(missing)
        return [self.vectors[k] for k in keys]


def cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right) or any(not math.isfinite(v) for v in left + right):
        raise DocMendError("Invalid embedding dimensions or values")
    norm = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
    return sum(a*b for a, b in zip(left, right)) / norm if norm else 0.0


def explicit(section: Section, unit: CodeUnit) -> bool:
    names = [unit.name, unit.name.rsplit(".", 1)[-1]]
    if unit.kind == "function":
        names += unit.facts.get("cli_names", [])
        names += [m for decorator in unit.facts.get("decorators", []) for m in re.findall(r"['\"](/[^'\"]+)['\"]", decorator)]
    return any(re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", section.text) for name in names)


def build_index(units: dict[str, CodeUnit], sections: dict[str, Section], *, embedder: Embedder | None = None, threshold: float = .78) -> dict:
    links = []
    unit_list, section_list = list(units.values()), list(sections.values())
    vectors = None
    if embedder and unit_list and section_list:
        vectors = embedder.embed([u.source for u in unit_list] + [s.text for s in section_list])
        if len(vectors) != len(unit_list) + len(section_list):
            raise DocMendError("Embedding response count mismatch")
    for j, section in enumerate(section_list):
        for i, unit in enumerate(unit_list):
            if explicit(section, unit):
                links.append({"unit": unit.id, "section": section.id, "method": "reference", "score": 1.0})
            elif vectors:
                score = cosine(vectors[i], vectors[len(unit_list)+j])
                if score >= threshold:
                    links.append({"unit": unit.id, "section": section.id, "method": "embedding", "score": score})
    graph = {"schema_version": 1, "units": [asdict(u) for u in unit_list], "sections": [asdict(s) for s in section_list], "links": links}
    import json
    graph["fingerprint"] = digest(json.dumps(graph, sort_keys=True))
    return graph
