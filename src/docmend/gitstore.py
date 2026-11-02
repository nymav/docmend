"""Read immutable Git blobs; never import, install, or execute target repository code."""
from __future__ import annotations

from pathlib import Path
import os
import re
import subprocess

from .config import Config
from .models import DocMendError


class GitStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.run("rev-parse", "--show-toplevel")

    def run(self, *args: str) -> bytes:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
        try:
            result = subprocess.run(["git", "-c", "safe.directory=" + str(self.root), "--no-pager", *args], cwd=self.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DocMendError("Git operation unavailable or timed out") from exc
        if result.returncode:
            raise DocMendError(f"Git {args[0]} failed; verify repository and commit references")
        return result.stdout

    def resolve(self, ref: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_./~^{}@+-]+", ref) or ref.startswith("-"):
            raise DocMendError("Unsafe Git reference")
        value = self.run("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", value):
            raise DocMendError("Expected an immutable commit identifier")
        return value

    def snapshot(self, sha: str, cfg: Config) -> dict[str, str]:
        result: dict[str, str] = {}
        total = 0
        entries = self.run("ls-tree", "-r", "-z", "--long", sha).split(b"\0")
        for entry in entries:
            if not entry:
                continue
            meta, raw_path = entry.split(b"\t", 1)
            mode, kind, oid, size = meta.split()
            path = raw_path.decode("utf-8", errors="strict")
            if mode not in (b"100644", b"100755") or kind != b"blob" or not cfg.accepts(path):
                continue
            if int(size) > cfg.max_file_bytes:
                raise DocMendError(f"File size limit exceeded: {path}")
            total += int(size)
            if len(result) >= cfg.max_files or total > cfg.max_total_bytes:
                raise DocMendError("Repository analysis budget exceeded")
            raw = self.run("cat-file", "blob", oid.decode())
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise DocMendError(f"Unsupported text encoding: {path}") from exc
            if "\0" in text:
                raise DocMendError(f"Binary data in text file: {path}")
            result[path] = text
        return result

    def changed_lines(self, base: str, head: str, paths: list[str]) -> tuple[str, list[dict]]:
        patches, hunks = [], []
        for path in paths:
            patch = self.run("diff", "--no-ext-diff", "--no-textconv", "--unified=0", base, head, "--", path).decode("utf-8", errors="replace")
            patches.append(patch)
            for match in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", patch, re.M):
                hunks.append({"path": path, "old_start": int(match[1]), "old_count": int(match[2] or 1), "new_start": int(match[3]), "new_count": int(match[4] or 1)})
        return "".join(patches), hunks

    def trusted_config(self, base: str, path: str = ".docmend.toml") -> Config:
        try:
            content = self.run("show", f"{base}:{path}").decode()
        except DocMendError:
            return Config()
        return Config.from_text(content)
