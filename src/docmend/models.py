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


# Fixed vocabulary for Finding.codes. Exactly one outcome code per finding,
# plus any number of change and hint codes. Teams filter or gate CI on these.
REASON_CODES = {
    # outcome
    "fixed-declared-fact": "A declared signature/default/config value was rewritten exactly from the new code",
    "detected-stale": "A declared value is provably out of date, but no edit is generated for this kind of section",
    "edit-rejected": "A computed edit failed the structural safety checks",
    "verified-current": "The declared value in the doc already matches the new code",
    "reverify-failed": "A rewrite was computed but did not re-check, so none is offered",
    "ambiguous-definition": "The code defines this name more than once; the active one is not inferred",
    "model-stale": "The model judged the section out of date",
    "model-accurate": "The model judged the section still correct",
    "model-uncertain": "The model could not decide",
    "low-confidence": "The model's stale verdict was below min_stale_confidence",
    "models-disagree": "Two model answers disagreed",
    "draft-rejected": "A model draft failed mechanical checks or the critic",
    "needs-review": "Linked code changed and no rule can prove the doc right or wrong",
    # what changed
    "contract-changed": "Signature, default, type or config value changed",
    "behaviour-changed": "Only the body changed; the interface is the same",
    "renamed": "The unit was renamed with an identical body",
    "added": "The unit is new",
    "removed": "The unit was deleted",
    "multiple-changes": "More than one linked unit changed; judged together",
    "ambiguous-name": "The short name matches several units",
    "docstring": "The section is a code docstring; DocMend never edits code",
    # hints for reviewers
    "old-value-in-prose": "The old value still appears in the section outside any declared fact",
    "no-declared-fact": "The section never states the value as Signature/Default, so it cannot be fixed automatically",
}


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
    # Ties a finding to this exact section text and these exact code changes.
    fingerprint: str = ""
    # True when a trusted baseline already acknowledged this exact review.
    acknowledged: bool = False
    # Machine-readable reasons from a fixed vocabulary (see REASON_CODES).
    codes: list[str] = field(default_factory=list)
    # Exact pointers a reviewer can check without rerunning anything: the doc
    # lines, each declared fact found there, and the code lines on both sides.
    card: dict[str, Any] = field(default_factory=dict)


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
    # Who/what produced this report: tool version, config hash, provider and
    # model names, and hashes (never contents) of every model exchange.
    provenance: dict[str, Any] = field(default_factory=dict)

    # True when a budget cut the analysis short; findings cover only part of it.
    incomplete: bool = False
    # Behaviour-only changes not reported because the section only mentions
    # the unit in passing (behaviour_scope = "subject").
    behaviour_mentions_skipped: int = 0
    # Body-only changes not reported because the section links to the unit
    # only through a short name several units share (skip_ambiguous_behaviour).
    ambiguous_links_skipped: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"
