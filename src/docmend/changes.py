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
    return result
