"""Durable local repair journal and explicit, conflict-aware crash rollback.

Journal contains original documentation; retain it privately until recovery completes.
"""
import json
import os
from pathlib import Path
from .models import DocMendError, digest

JOURNAL = '.docmend-recovery.json'
LOCK = '.docmend-apply.lock'


def write_journal(root: Path, originals: dict, replacements: dict) -> None:
    path = root / JOURNAL
    payload = json.dumps({'version':1,'files':[{'path':p,'before':text,'after_hash':digest(replacements[p]),'before_hash':digest(text)} for p,text in originals.items()]})
    # Exclusive creation prevents replacing an unresolved recovery record.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as stream:
        stream.write(payload);stream.flush();os.fsync(stream.fileno())
    sync_directory(root)


def sync_directory(root: Path) -> None:
    fd=os.open(root,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def clear_journal(root: Path) -> None:
    (root/JOURNAL).unlink(missing_ok=True)
    sync_directory(root)


def recover_local(root: Path, *, confirm_no_active_writer: bool = False) -> list[str]:
    from .repair import safe_path, atomic_write
    root=root.resolve()
    if not confirm_no_active_writer:
        raise DocMendError('Stop all repair writers, then explicitly confirm no active writer before recovery')
    journal=safe_path(root,JOURNAL)
    try:
        raw=json.loads(journal.read_text())
        if raw['version']!=1 or not isinstance(raw['files'],list) or not raw['files']:raise ValueError()
        entries=raw['files'];seen=set()
        # All files must pass preflight before restoring any file.
        for entry in entries:
            name=entry['path'];path=safe_path(root,name)
            if name in seen or not name.endswith(('.md','.mdx')):raise ValueError()
            seen.add(name)
            if digest(entry['before'])!=entry['before_hash']:raise ValueError()
            current=digest(path.read_bytes().decode('utf-8'))
            if current not in (entry['before_hash'],entry['after_hash']):
                raise DocMendError(f'Concurrent edit detected: {name}; preserve the journal and recover manually')
        for entry in entries:
            path=safe_path(root,entry['path'])
            if digest(path.read_bytes().decode('utf-8')) not in (entry['before_hash'],entry['after_hash']):
                raise DocMendError('Documentation changed during recovery; journal retained')
            atomic_write(path,entry['before'])
        clear_journal(root)
        safe_path(root,LOCK).unlink(missing_ok=True)
        return [e['path'] for e in entries]
    except (KeyError,ValueError,TypeError) as exc:
        raise DocMendError('Invalid recovery journal; no automatic recovery permitted') from exc
