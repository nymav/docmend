"""JavaScript and TypeScript contracts from tree-sitter syntax trees.

Optional: install ``docmend[js]``. Source is parsed, never executed.
"""
from __future__ import annotations

import json
import re

from .models import CodeUnit, DocMendError, digest

JS_SUFFIXES = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")

try:
    import tree_sitter
    import tree_sitter_javascript
    import tree_sitter_typescript
except ImportError:  # pragma: no cover - exercised when the extra is absent
    tree_sitter = None

_parsers: dict[str, object] = {}


def available() -> bool:
    return tree_sitter is not None


def _parser(path: str):
    kind = "tsx" if path.endswith(".tsx") else "ts" if path.endswith((".ts", ".mts", ".cts")) else "js"
    if kind not in _parsers:
        lang = {"js": tree_sitter_javascript.language, "ts": tree_sitter_typescript.language_typescript,
                "tsx": tree_sitter_typescript.language_tsx}[kind]()
        _parsers[kind] = tree_sitter.Parser(tree_sitter.Language(lang))
    return _parsers[kind]


def _text(node) -> str:
    return node.text.decode("utf-8") if node is not None else None


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("( ", "(").replace(" )", ")").strip()


def _tokens(node) -> str:
    # Whitespace and comments do not change behaviour.
    out = []
    def walk(n):
        if n.type == "comment":
            return
        if n.child_count == 0:
            out.append(n.type + ":" + _text(n))
        for c in n.children:
            walk(c)
    if node is not None:
        walk(node)
    return " ".join(out)


def _params(node) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for p in node.named_children if node is not None else []:
        if p.type == "comment":
            continue
        pattern, value = p.child_by_field_name("pattern"), p.child_by_field_name("value")
        if p.type == "assignment_pattern":
            pattern, value = p.child_by_field_name("left"), p.child_by_field_name("right")
        elif p.type in ("identifier", "rest_pattern", "object_pattern", "array_pattern"):
            pattern = p
        result[_squash(_text(pattern or p))] = _squash(_text(value)) if value is not None else None
    return result


def parse_js(path: str, text: str) -> list[CodeUnit]:
    if not available():
        raise DocMendError("JavaScript/TypeScript support needs the optional docmend[js] extra")
    source = text.encode("utf-8")
    tree = _parser(path).parse(source)
    if tree.root_node.has_error:
        raise DocMendError(f"Cannot parse JavaScript/TypeScript source: {path}")
    lines = text.splitlines(keepends=True)
    units: list[CodeUnit] = []

    def span(node):
        return node.start_point[0] + 1, node.end_point[0] + 1

    def function(name, node, outer, exported):
        params = node.child_by_field_name("parameters")
        if params is None and node.child_by_field_name("parameter") is not None:
            single = node.child_by_field_name("parameter")
            plist = {_text(single): None}
            ptext = "(" + _text(single) + ")"
        else:
            plist, ptext = _params(params), _squash(_text(params)) if params is not None else "()"
        short = name.rsplit(".", 1)[-1]
        signature = short + ptext
        ret = node.child_by_field_name("return_type")
        is_async = any(c.type == "async" for c in node.children)
        contract = json.dumps({"signature": signature, "return": _squash(_text(ret)).lstrip(": ") if ret is not None else None,
                               "async": is_async, "exported": exported}, sort_keys=True)
        start, end = span(outer)
        units.append(CodeUnit(f"{path}::{name}", path, name, "function", start, end, "".join(lines[start-1:end]),
                              contract, digest(_tokens(node.child_by_field_name("body"))),
                              {"signature": signature, "params": plist, "decorators": [], "cli_names": [], "language": "javascript"}))

    def klass(node, outer, exported, prefix=""):
        name = prefix + _text(node.child_by_field_name("name"))
        heritage = [_squash(_text(c)) for c in node.named_children if c.type == "class_heritage"]
        fields, members = {}, []
        for m in node.child_by_field_name("body").named_children:
            if m.type in ("public_field_definition", "field_definition"):
                key = m.child_by_field_name("name") or m.child_by_field_name("property")
                ann, val = m.child_by_field_name("type"), m.child_by_field_name("value")
                fields[_text(key)] = {"annotation": _squash(_text(ann)).lstrip(": ") if ann is not None else None,
                                      "value": _squash(_text(val)) if val is not None else None}
            elif m.type == "method_definition":
                members.append(m)
        contract = json.dumps({"bases": heritage, "fields": fields, "exported": exported}, sort_keys=True)
        start, end = span(outer)
        units.append(CodeUnit(f"{path}::{name}", path, name, "class", start, end, "".join(lines[start-1:end]),
                              contract, digest(contract), {"fields": fields, "language": "javascript"}))
        for m in members:
            function(name + "." + _text(m.child_by_field_name("name")), m, m, exported)

    def declaration(node, outer, exported):
        if node.type in ("function_declaration", "generator_function_declaration"):
            function(_text(node.child_by_field_name("name")), node, outer, exported)
        elif node.type in ("class_declaration", "abstract_class_declaration"):
            klass(node, outer, exported)
        elif node.type in ("lexical_declaration", "variable_declaration"):
            for d in node.named_children:
                if d.type != "variable_declarator":
                    continue
                name, value = d.child_by_field_name("name"), d.child_by_field_name("value")
                if name is None or name.type != "identifier" or value is None:
                    continue
                if value.type in ("arrow_function", "function_expression", "function"):
                    function(_text(name), value, outer, exported)
                elif _text(name).isupper() and value.type in ("number", "string", "true", "false", "null", "template_string"):
                    val = _squash(_text(value))
                    contract = json.dumps({"value": val}, sort_keys=True)
                    start, end = span(outer)
                    units.append(CodeUnit(f"{path}::{_text(name)}", path, _text(name), "config", start, end,
                                          "".join(lines[start-1:end]), contract, digest(contract),
                                          {"value": val, "language": "javascript"}))

    for node in tree.root_node.named_children:
        if node.type == "export_statement":
            inner = node.child_by_field_name("declaration")
            if inner is not None:
                declaration(inner, node, True)
        else:
            declaration(node, node, False)
    return units
