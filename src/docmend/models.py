"""Typed contracts shared by parsers, analysis, repair and adapters."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any


class DocMendError(Exception):
    """An expected, user-actionable failure; no partial result is success."""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CodeUnit:
    id: str
    path: str
    name: str
    kind: str
    line: int
    end_line: int
    source: str
    contract: str
    semantic: str
    facts: dict[str, Any]


@dataclass(frozen=True)
class Section:
    id: str
    path: str
    heading: str
    start: int
    end: int
    text: str
    file_hash: str


@dataclass(frozen=True)
class Change:
    kind: str
    before: CodeUnit | None
    after: CodeUnit | None

    @property
    def unit(self) -> CodeUnit:
        unit = self.after or self.before
        assert unit is not None
        return unit


@dataclass
class Finding:
    section_id: str
    path: str
    heading: str
    status: str  # stale / accurate / review
    reason: str
    unit_ids: list[str]
    confidence: float = 0.0
    evidence: str = "static"


@dataclass
class Edit:
    section_id: str
    path: str
    start: int
    end: int
    before: str
    after: str
    file_hash: str
    mode: str  # safe / draft
    reason: str
    evidence: str = "static"


@dataclass
class Report:
    base: str
    head: str
    index_hash: str
    changes: list[dict[str, Any]]
    findings: list[Finding] = field(default_factory=list)
    edits: list[Edit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"
