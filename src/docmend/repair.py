"""Bounded edits, exact-file preconditions and rollback on local write failures."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path, PurePosixPath
import os
import re
import tempfile

from .docparse import headings
from .recovery import JOURNAL, write_journal, clear_journal, sync_directory
from .models import DocMendError, Edit, digest


def validate_edit(edit: Edit) -> None:
    if not isinstance(edit.path, str) or type(edit.start) is not int or type(edit.end) is not int or not all(isinstance(x,str) for x in (edit.before,edit.after,edit.file_hash)):
        raise DocMendError("Malformed repair field types")
    p = PurePosixPath(edit.path)
    if p.is_absolute() or ".." in p.parts or "\\" in edit.path or not edit.path.endswith((".md", ".mdx")) or any(x == ".git" for x in p.parts):
        raise DocMendError("Repair target must be a repository-relative Markdown file")
    if edit.mode not in ("safe", "draft") or edit.evidence not in ("static", "model"):
        raise DocMendError("Unknown repair mode/evidence")
    if edit.mode == "safe" and edit.evidence != "static":
        raise DocMendError("Model-only edits cannot be automatically approved")
    if edit.start < 0 or edit.end <= edit.start or edit.before == edit.after or not edit.after.strip():
        raise DocMendError("Invalid or empty repair span")
    if [h for _, h in headings(edit.before)] != [h for _, h in headings(edit.after)]:
        raise DocMendError("Repair must preserve section headings")
    fences = lambda text: re.findall(r"^ {0,3}(?:`{3,}|~{3,}).*$", text, re.M)
    if fences(edit.before) != fences(edit.after):
        raise DocMendError("Repair must preserve code fence structure")
    links = lambda text: re.findall(r"\]\(([^)]+)\)", text)
    if links(edit.before) != links(edit.after):
        raise DocMendError("Repair must preserve existing link targets")
    if edit.before.endswith("\n") != edit.after.endswith("\n"):
        raise DocMendError("Repair must preserve trailing newline convention")
    if len(edit.after) > max(1000, len(edit.before)*2):
        raise DocMendError("Repair size exceeds the allowed growth budget")


def patched_files(files: dict[str, str], edits: list[Edit], *, include_drafts: bool = False) -> dict[str, str]:
    grouped: dict[str, list[Edit]] = defaultdict(list)
    for edit in edits:
        validate_edit(edit)
        if edit.mode == "safe" or include_drafts:
            grouped[edit.path].append(edit)
    result = {}
    for path, changes in grouped.items():
        if path not in files:
            raise DocMendError(f"Repair target missing: {path}")
        original = files[path]
        lines = original.splitlines(keepends=True)
        previous_end = -1
        for edit in sorted(changes, key=lambda x: x.start):
            if digest(original) != edit.file_hash or "".join(lines[edit.start:edit.end]) != edit.before:
                raise DocMendError(f"Stale repair precondition: {path}")
            if edit.start < previous_end or edit.end > len(lines):
                raise DocMendError("Overlapping or out-of-range repairs")
            previous_end = edit.end
        for edit in sorted(changes, key=lambda x: x.start, reverse=True):
            lines[edit.start:edit.end] = [edit.after]
        result[path] = "".join(lines)
    return result


def safe_path(root: Path, relative: str) -> Path:
    p = PurePosixPath(relative)
    if p.is_absolute() or ".." in p.parts or "\\" in relative or ".git" in p.parts:
        raise DocMendError("Unsafe repository-relative output path")
    target = root / relative
    cursor = root
    for part in p.parts:
        cursor /= part
        if cursor.is_symlink():
            raise DocMendError("Symlinks are not valid read/write targets")
    if not target.resolve().is_relative_to(root.resolve()):
        raise DocMendError("Target escaped repository root")
    return target


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".docmend-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def apply_local(root: Path, edits: list[Edit], *, include_drafts: bool = False) -> list[str]:
    root = root.resolve()
    if (root / JOURNAL).exists() or (root / JOURNAL).is_symlink():
        raise DocMendError("Unresolved repair journal; run explicit recovery before another apply")
    lock = root / ".docmend-apply.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise DocMendError("Another repair is active, or a stale lock needs inspection") from exc
    originals = {}
    written = []
    journal_ready = False
    try:
        os.close(fd)
        selected = [e for e in edits if e.mode == "safe" or include_drafts]
        for edit in selected:
            path = safe_path(root, edit.path)
            if not path.is_file():
                raise DocMendError(f"Missing repair file: {edit.path}")
            originals[edit.path] = path.read_bytes().decode("utf-8")
        replacements = patched_files(originals, selected, include_drafts=include_drafts)
        if replacements:
            write_journal(root, originals, replacements)
            journal_ready = True
        for name, value in replacements.items():
            path = safe_path(root, name)
            # Detect changes after preflight, before committing each file.
            if path.read_bytes().decode("utf-8") != originals[name]:
                raise DocMendError("Documentation changed during apply")
            written.append(name)
            atomic_write(path, value)
        if journal_ready:
            clear_journal(root)
        return written
    except Exception:
        for name in reversed(written):
            path = safe_path(root, name)
            current = path.read_bytes().decode("utf-8")
            if current not in (replacements[name], originals[name]):
                raise DocMendError("Concurrent edit detected during rollback; manual recovery required")
            if current != originals[name]:
                atomic_write(path, originals[name])
        if journal_ready:
            clear_journal(root)
        raise
    finally:
        lock.unlink(missing_ok=True)
