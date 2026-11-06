"""Python AST and TOML semantic contracts. Analysis does not execute source files."""
from __future__ import annotations

import ast
import json
import tomllib

from .models import CodeUnit, DocMendError, digest
from .adapters import parse_json


def _literal(node: ast.AST | None) -> str | None:
    return ast.unparse(node) if node is not None else None


def _body(nodes: list[ast.stmt]) -> str:
    nodes = list(nodes)
    if nodes and isinstance(nodes[0], ast.Expr) and isinstance(nodes[0].value, ast.Constant) and isinstance(nodes[0].value.value, str):
        nodes = nodes[1:]
    return ast.dump(ast.Module(body=nodes, type_ignores=[]), include_attributes=False)


def parse_python(path: str, text: str) -> list[CodeUnit]:
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise DocMendError(f"Cannot parse Python source: {path}") from exc
    lines = text.splitlines(keepends=True)
    units: list[CodeUnit] = []

    def visit(node: ast.AST, prefix: str = "") -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = prefix + node.name
            args = node.args
            positional = args.posonlyargs + args.args
            defaults: dict[str, str | None] = {a.arg: None for a in positional}
            for a, value in zip(positional[len(positional) - len(args.defaults):], args.defaults):
                defaults[a.arg] = _literal(value)
            defaults.update({a.arg: _literal(v) for a, v in zip(args.kwonlyargs, args.kw_defaults)})
            signature = node.name + "(" + ast.unparse(args) + ")"
            decorators = [ast.unparse(d) for d in node.decorator_list]
            cli_names = []
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr in ("command", "group", "option", "argument"):
                    cli_names += [a.value for a in decorator.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                    cli_names += [k.value.value for k in decorator.keywords if k.arg == "name" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)]
            contract = json.dumps({"signature": signature, "return": _literal(node.returns), "decorators": decorators, "async": isinstance(node, ast.AsyncFunctionDef)}, sort_keys=True)
            start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
            units.append(CodeUnit(f"{path}::{name}", path, name, "function", start, node.end_lineno or node.lineno, "".join(lines[start-1:node.end_lineno]), contract, digest(_body(node.body)), {"signature": signature, "params": defaults, "decorators": decorators, "cli_names": cli_names}))
        elif isinstance(node, ast.ClassDef):
            name = prefix + node.name
            fields = {n.target.id: {"annotation": _literal(n.annotation), "value": _literal(n.value)} for n in node.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
            contract = json.dumps({"bases": [ast.unparse(b) for b in node.bases], "fields": fields, "decorators": [ast.unparse(d) for d in node.decorator_list]}, sort_keys=True)
            start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
            units.append(CodeUnit(f"{path}::{name}", path, name, "class", start, node.end_lineno or node.lineno, "".join(lines[start-1:node.end_lineno]), contract, digest(contract), {"fields": fields}))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    visit(child, name + ".")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    value = _literal(node.value)
                    contract = json.dumps({"value": value}, sort_keys=True)
                    units.append(CodeUnit(f"{path}::{target.id}", path, target.id, "config", node.lineno, node.end_lineno or node.lineno, "".join(lines[node.lineno-1:node.end_lineno]), contract, digest(contract), {"value": value}))
    for node in tree.body:
        visit(node)
    return units


def parse_toml(path: str, text: str) -> list[CodeUnit]:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DocMendError(f"Cannot parse TOML: {path}") from exc
    units = []
    def walk(values: dict, prefix: str = "") -> None:
        for key, value in values.items():
            name = prefix + key
            if isinstance(value, dict):
                walk(value, name + ".")
            else:
                val = json.dumps(value, sort_keys=True, default=str)
                units.append(CodeUnit(f"{path}::{name}", path, name, "config", 1, len(text.splitlines()), f"{name} = {val}", val, digest(val), {"value": val}))
    walk(document)
    return units


def parse_code(files: dict[str, str], *, review_duplicates: bool = False) -> dict[str, CodeUnit]:
    units = []
    for path, text in sorted(files.items()):
        if path.endswith(".py"):
            units.extend(parse_python(path, text))
        elif path.endswith(".json"):
            units.extend(parse_json(path, text))
        elif path.endswith(".toml") and not path.endswith(".docmend.toml"):
            units.extend(parse_toml(path, text))
    groups: dict[str, list[CodeUnit]] = {}
    for unit in units:
        groups.setdefault(unit.id, []).append(unit)
    duplicates = {key for key, group in groups.items() if len(group) > 1}
    if duplicates and not review_duplicates:
        raise DocMendError("Duplicate code-unit definitions are ambiguous; disambiguate before analysis")
    # Never select a presumed runtime binding. Keep every definition as evidence
    # under one ambiguous unit, including methods of repeated class definitions.
    repeated_classes = {u.id for u in units if u.id in duplicates and u.kind == "class"}
    result = {}
    for key, group in groups.items():
        if key in duplicates or any(key.startswith(parent + ".") for parent in repeated_classes):
            first = group[0]
            contract = json.dumps([u.contract for u in group])
            semantic = digest(json.dumps([u.semantic for u in group]))
            result[key] = CodeUnit(key, first.path, first.name, "ambiguous", first.line,
                max(u.end_line for u in group), "\n\n".join(u.source for u in group),
                contract, semantic, {"definition_lines": [u.line for u in group],
                "reason": "Repeated definition or member of a repeated class; active binding is not inferred"})
        else:
            result[key] = group[0]
    return result
