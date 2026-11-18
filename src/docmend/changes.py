"""AST-aware change classification; comments and whitespace do not create drift."""
from .models import Change, CodeUnit


def classify(before: dict[str, CodeUnit], after: dict[str, CodeUnit]) -> list[Change]:
    result = []
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if old is None:
            result.append(Change("added", None, new))
        elif new is None:
            result.append(Change("removed", old, None))
        elif old.contract != new.contract:
            result.append(Change("contract", old, new))
        elif old.semantic != new.semantic:
            result.append(Change("behaviour", old, new))
    return _pair_renames(result)


def _pair_renames(changes: list[Change]) -> list[Change]:
    """Pair a removed and an added function/class with an identical body.

    Only one-to-one matches count; if a body fingerprint has several removed
    or added candidates, nothing is paired and both stay add/remove reviews.
    """
    kinds = ("function", "class")
    removed = {}
    added = {}
    for c in changes:
        if c.kind == "removed" and c.before.kind in kinds:
            removed.setdefault((c.before.kind, c.before.semantic), []).append(c)
        elif c.kind == "added" and c.after.kind in kinds:
            added.setdefault((c.after.kind, c.after.semantic), []).append(c)
    pairs = {}
    for key, olds in removed.items():
        news = added.get(key, [])
        if len(olds) == 1 and len(news) == 1:
            pairs[id(olds[0])] = Change("renamed", olds[0].before, news[0].after)
            pairs[id(news[0])] = None
    return [pairs[id(c)] if id(c) in pairs else c for c in changes if pairs.get(id(c), c) is not None]
