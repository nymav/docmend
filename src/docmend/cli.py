"""CLI and exit-code contract. Remote writes are a separate, explicit command."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

from . import __version__
from .config import Config
from .gitstore import GitStore
from .github import GitHub
from .models import DocMendError, Edit
from .pipeline import analyze_repository
from .repair import apply_local
from .reporting import save, summary


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="docmend", description="Detect documentation drift without executing repository code")
    p.add_argument("--version", action="version", version=__version__)
    subs = p.add_subparsers(dest="command", required=True)
    for command in ("index", "check", "publish"):
        sub = subs.add_parser(command)
        sub.add_argument("--repo", type=Path, default=Path.cwd())
        sub.add_argument("--base", required=True)
        sub.add_argument("--head", default="HEAD")
        sub.add_argument("--output", default=".docmend/report")
        sub.add_argument("--llm", action="store_true", help="Explicitly send bounded code/doc evidence to the configured provider")
        sub.add_argument("--semantic", action="store_true", help="Use real embedding vectors from the configured provider")
        if command == "check":
            sub.add_argument("--fail-on", choices=("review", "stale", "never"), default="review")
        if command == "publish":
            sub.add_argument("--repository", required=True)
            sub.add_argument("--pr", type=int, required=True)
            sub.add_argument("--include-drafts", action="store_true")
    sub = subs.add_parser("apply")
    sub.add_argument("--repo", type=Path, default=Path.cwd())
    sub.add_argument("--report", type=Path, required=True)
    sub.add_argument("--include-drafts", action="store_true", help="Apply model drafts only after explicit human review")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        store = GitStore(args.repo)
        if args.command == "apply":
            raw = json.loads(args.report.read_text())
            if raw.get("schema_version") != 1:
                raise DocMendError("Unsupported report schema")
            if store.resolve("HEAD") != raw["head"]:
                raise DocMendError("HEAD differs from the analyzed commit")
            report, _, _ = analyze_repository(store, raw["base"], raw["head"])
            edits = [Edit(**e) for e in raw["edits"]]
            permitted = [asdict(e) for e in report.edits]
            for edit in edits:
                if edit.mode == "safe" and asdict(edit) not in permitted:
                    raise DocMendError("Safe repair is not reproducible from current code facts")
            written = apply_local(store.root, edits, include_drafts=args.include_drafts)
            print(json.dumps({"applied": written}))
            return 0
        report, graph, files = analyze_repository(store, args.base, args.head, llm=args.llm, semantic=args.semantic)
        save(store.root, args.output, report, graph, files)
        if args.command == "publish":
            token = os.environ.get("DOCMEND_GITHUB_TOKEN", "")
            value = GitHub(args.repository, token).publish(args.pr, report, files, include_drafts=args.include_drafts)
            print(json.dumps(value))
            return 0
        counts = summary(report)
        print(json.dumps({"version": __version__, "base": report.base, "head": report.head, "output": args.output, **counts}))
        if args.command == "index":
            return 0
        if args.fail_on == "never":
            return 0
        if counts["stale"] or (args.fail_on == "review" and (counts["review"] or counts["coverage_gaps"])):
            return 2
        return 0
    except (DocMendError, OSError, ValueError, TypeError, KeyError) as exc:
        # Config/format failures are operational errors, never a clean pass.
        print(json.dumps({"error": str(exc), "exit_code": 3}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
