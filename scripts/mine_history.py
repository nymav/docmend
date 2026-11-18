"""Mine a repository's history for real documentation drift and score DocMend on it.

For each first-parent commit C that changes Python code but not a linked doc
section, DocMend analyses (C^, C) exactly as it would in a pull request. A
flagged section is then followed forward for --window commits: if a human
later rewrites that section, the flag is "confirmed by history", and if
DocMend proposed a safe fix, we check whether the human's later text contains
the same corrected line ("fix agreement").

Labels mined this way are silver, not gold: a later edit may be unrelated,
and an unedited section may still be stale. Treat the numbers as real-world
evidence to read alongside the hand-labelled suites, not as accuracy.

Usage: python scripts/mine_history.py REPO_PATH [--commits 400] [--window 30] [--output DIR]
Read-only: uses `git show`/`git diff` on an existing clone; never checks out or writes to it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from docmend.config import Config  # noqa: E402
from docmend.docparse import parse_docs  # noqa: E402
from docmend.models import DocMendError  # noqa: E402
from docmend.pipeline import analyze_files  # noqa: E402

DOC = (".md", ".mdx", ".rst")


def git(repo, *args) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True).stdout.decode("utf-8", "replace")


def show(repo, rev, path, cache):
    key = (rev, path)
    if key not in cache:
        try:
            cache[key] = git(repo, "show", f"{rev}:{path}")
        except subprocess.CalledProcessError:
            cache[key] = None
    return cache[key]


def sections_at(repo, rev, path, cache, parsed):
    key = (rev, path)
    if key not in parsed:
        text = show(repo, rev, path, cache)
        parsed[key] = None if text is None else {k: v.text for k, v in parse_docs({path: text}).items()}
    return parsed[key]


def later_edit(repo, commits, start, window, path, sid, text_now, cache, parsed):
    """First later commit (within window) whose version of this section differs."""
    for later in commits[start: start + window]:
        secs = sections_at(repo, later, path, cache, parsed)
        if secs is None or sid not in secs:
            return None  # file or heading gone: cannot follow it reliably
        if secs[sid] != text_now:
            return later
    return None


def repo_config(repo, rev, cache):
    """The repository's own .docmend.toml at this commit, else defaults, as a real run would use."""
    text = show(repo, rev, ".docmend.toml", cache)
    try:
        return Config.from_text(text) if text else Config()
    except DocMendError:
        return Config()


def doc_paths(repo, rev, cfg):
    return [p for p in git(repo, "ls-tree", "-r", "--name-only", rev).splitlines() if p.endswith(DOC) and cfg.accepts(p)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo")
    ap.add_argument("--commits", type=int, default=400)
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--output", default="artifacts/history")
    ap.add_argument("--behaviour-scope", choices=["subject", "all"], help="Override behaviour_scope (to measure its effect)")
    ap.add_argument("--keep-history-docs", action="store_true", help="Also check changelogs (to measure their effect)")
    a = ap.parse_args(argv)
    repo = a.repo
    commits = git(repo, "rev-list", "--first-parent", "--no-merges", f"-n{a.commits}", "HEAD").split()[::-1]
    index = {c: i for i, c in enumerate(commits)}
    cache: dict = {}
    parsed: dict = {}
    rows, stats = [], Counter()
    baseline = Counter()
    for c in commits[1:]:
        parent = git(repo, "rev-parse", f"{c}^").strip()
        changed = git(repo, "diff", "--name-only", "--no-renames", parent, c).splitlines()
        cfg = repo_config(repo, c, cache)
        if a.keep_history_docs:
            from dataclasses import replace
            cfg = replace(cfg, skip_history_docs=False)
        if a.behaviour_scope:
            from dataclasses import replace as _r
            cfg = _r(cfg, behaviour_scope=a.behaviour_scope)
        code = [p for p in changed if p.endswith(".py") and cfg.accepts(p)]
        if not code:
            continue
        stats["code_commits"] += 1
        docs = doc_paths(repo, c, cfg)
        before = {p: t for p in code + docs if (t := show(repo, parent, p, cache)) is not None}
        after = {p: t for p in code + docs if (t := show(repo, c, p, cache)) is not None}
        try:
            report, _ = analyze_files(before, after, base=parent, head=c, cfg=cfg)
        except DocMendError as exc:
            stats["skipped_" + type(exc).__name__] += 1
            continue
        except Exception:  # unparsable history is common; count it, keep going
            stats["skipped_error"] += 1
            continue
        stats["contract_changes"] += sum(ch["kind"] in ("contract", "renamed", "removed") for ch in report.to_dict()["changes"])
        edits = {e.section_id: e for e in report.edits}
        for f in report.findings:
            if f.status not in ("stale", "review") or f.path in changed:
                continue  # the author already touched this doc in the same commit
            stats["flagged_" + f.status] += 1
            now = sections_at(repo, c, f.path, cache, parsed) or {}
            if f.section_id not in now:
                continue
            fixed_by = later_edit(repo, commits, index[c] + 1, a.window, f.path, f.section_id, now[f.section_id], cache, parsed)
            human_text = sections_at(repo, fixed_by, f.path, cache, parsed)[f.section_id] if fixed_by else None
            row = {"commit": c, "section": f.section_id, "status": f.status, "codes": f.codes,
                   "units": f.unit_ids, "human_edit": fixed_by}
            e = edits.get(f.section_id)
            if e:
                added = [l for l in e.after.splitlines() if l not in e.before.splitlines()]
                row["docmend_fix"] = added
                row["fix_agrees"] = bool(human_text) and all(l in human_text.splitlines() for l in added)
            rows.append(row)
        # Baseline: sections in this commit's docs that DocMend did NOT flag and
        # that this commit did not touch. Their later-edit rate is the chance level.
        flagged_ids = {f.section_id for f in report.findings}
        for path in docs:
            if path in changed:
                continue
            for sid, text in (sections_at(repo, c, path, cache, parsed) or {}).items():
                if sid in flagged_ids:
                    continue
                baseline["sections"] += 1
                baseline["edited"] += bool(later_edit(repo, commits, index[c] + 1, a.window, path, sid, text, cache, parsed))
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    flagged = len(rows)
    confirmed = sum(1 for r in rows if r["human_edit"])
    fixes = [r for r in rows if "docmend_fix" in r]
    summary = {
        "repo_head": git(repo, "rev-parse", "HEAD").strip(), "commits_scanned": len(commits), "window": a.window,
        **stats, "flagged_sections": flagged, "confirmed_by_later_human_edit": confirmed,
        "confirmation_rate": round(confirmed / flagged, 3) if flagged else None,
        "safe_fixes": len(fixes), "fixes_with_later_human_edit": sum(1 for r in fixes if r["human_edit"]),
        "fixes_matching_human": sum(1 for r in fixes if r.get("fix_agrees")),
        "baseline_unflagged_sections": baseline["sections"],
        "baseline_later_edit_rate": round(baseline["edited"] / baseline["sections"], 3) if baseline["sections"] else None,
        "label_quality": "silver: inferred from later edits, not human-verified",
    }
    (out / "cases.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
