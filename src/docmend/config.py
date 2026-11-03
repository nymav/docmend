"""Strict bounded configuration. Credentials are environment references, never values."""
from dataclasses import dataclass, fields
from fnmatch import fnmatch
from pathlib import PurePosixPath
import math
import tomllib
from urllib.parse import urlsplit

from .models import DocMendError


@dataclass(frozen=True)
class Config:
    include: tuple[str, ...] = ("*.py", "*.md", "*.mdx", "*.toml")
    exclude: tuple[str, ...] = (".git/*", "tests/*", "test/*", "*/tests/*", "*/test_*", ".venv/*", "venv/*", "node_modules/*", "vendor/*")
    max_files: int = 2000
    max_file_bytes: int = 500_000
    max_total_bytes: int = 10_000_000
    max_sections: int = 100
    similarity_threshold: float = 0.78
    endpoint: str = ""
    model: str = ""
    embedding_model: str = ""
    api_key_env: str = "DOCMEND_API_KEY"
    timeout_seconds: int = 30
    max_prompt_chars: int = 24000
    analysis_timeout_seconds: int = 120
    max_provider_requests: int = 50

    def accepts(self, path: str) -> bool:
        p = PurePosixPath(path)
        if p.is_absolute() or ".." in p.parts or "\\" in path:
            return False
        return any(fnmatch(path, pat) for pat in self.include) and not any(fnmatch(path, pat) for pat in self.exclude)

    @classmethod
    def from_text(cls, text: str) -> "Config":
        try:
            values = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise DocMendError("Invalid TOML configuration") from exc
        unknown = set(values) - {f.name for f in fields(cls)}
        if unknown:
            raise DocMendError(f"Unknown config keys: {', '.join(sorted(unknown))}")
        for key in ("include", "exclude"):
            if key in values:
                if not isinstance(values[key], list) or not all(isinstance(x, str) for x in values[key]):
                    raise DocMendError(f"{key} must be a list of strings")
                values[key] = tuple(values[key])
        cfg = cls(**values)
        for key, upper in [("max_files", 10000), ("max_file_bytes", 2_000_000), ("max_total_bytes", 50_000_000), ("max_sections", 500), ("timeout_seconds", 120), ("max_prompt_chars", 100000), ("analysis_timeout_seconds", 900), ("max_provider_requests", 500)]:
            val = getattr(cfg, key)
            if type(val) is not int or not 1 <= val <= upper:
                raise DocMendError(f"{key} must be between 1 and {upper}")
        if not isinstance(cfg.similarity_threshold, (float, int)) or not math.isfinite(cfg.similarity_threshold) or not 0 <= cfg.similarity_threshold <= 1:
            raise DocMendError("similarity_threshold must be a finite number in [0,1]")
        for key in ("endpoint", "model", "embedding_model", "api_key_env"):
            if not isinstance(getattr(cfg, key), str):
                raise DocMendError(f"{key} must be a string")
        if cfg.endpoint:
            u = urlsplit(cfg.endpoint)
            if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise DocMendError("Provider endpoint must be an HTTPS URL without credentials, query or fragment")
        if not cfg.api_key_env.isidentifier():
            raise DocMendError("api_key_env must be an environment variable name")
        return cfg
