"""Static source adapters with one-based inclusive source-span contracts.

JSON configuration is opt-in through include patterns. No target code executes.
"""
import json
import re
from .models import CodeUnit, DocMendError, digest

SUPPORTED_SUFFIXES = ('.py', '.toml', '.json', '.md', '.mdx')


def parse_json(path: str, text: str) -> list[CodeUnit]:
    decoder = json.JSONDecoder(parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    units = []
    def unique(pairs):
        result = {}
        for name, val in pairs:
            if name in result: raise ValueError('Duplicate key')
            result[name] = val
        return result

    def skip(i):
        while i < len(text) and text[i].isspace(): i += 1
        return i

    def value(i, keys):
        i = skip(i)
        if i >= len(text): raise ValueError('Missing value')
        if text[i] == '{':
            i = skip(i + 1); seen = set()
            if i < len(text) and text[i] == '}': return i + 1
            while True:
                name, end = decoder.raw_decode(text, i)
                if not isinstance(name, str) or name in seen: raise ValueError('Invalid or duplicate key')
                seen.add(name); i = skip(end)
                if text[i:i+1] != ':': raise ValueError('Missing colon')
                i = skip(value(i + 1, keys + [name]))
                if text[i:i+1] == '}': return i + 1
                if text[i:i+1] != ',': raise ValueError('Missing comma')
                i = skip(i + 1)
        start = i
        parsed, end = decoder.raw_decode(text, i)
        # Arrays are a single contract, not unstable position-based symbol IDs.
        canonical = json.dumps(parsed, sort_keys=True, ensure_ascii=False, allow_nan=False)
        pointer = '/' + '/'.join(k.replace('~','~0').replace('/','~1') for k in keys)
        # Safe dotted identifiers can participate in existing explicit config rules.
        name = '.'.join(keys) if keys and all(re.fullmatch(r'[A-Za-z_]\w*', k) for k in keys) else pointer
        units.append(CodeUnit(f'{path}::{pointer}', path, name, 'config', text.count('\n',0,start)+1,
                              text.count('\n',0,end)+1, text[start:end], canonical, digest(canonical), {'value':canonical,'pointer':pointer}))
        return end
    try:
        json.loads(text, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
        end = value(0, [])
        if skip(end) != len(text): raise ValueError('Trailing content')
    except (ValueError, TypeError, IndexError, RecursionError) as exc:
        raise DocMendError(f'Cannot parse JSON source: {path}') from exc
    return units
