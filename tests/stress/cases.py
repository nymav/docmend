"""Labelled stress cases. Each case is one code change and one doc.

truth  : "stale" if the doc is now wrong, "ok" if it is still right.
expect : what DocMend should do today: "fixed" (safe edit equal to gold),
         "review" (flagged for a person), or "quiet" (no stale/review finding).
gold   : for "fixed", the exact doc text after the correct repair.

Hard guarantees (never relaxed): an "ok" doc is never edited or called stale;
a "stale" doc is never quiet; every edit equals gold. "expect" is a regression
pin: improving DocMend means updating it here on purpose.
"""
CASES = []


def case(name, truth, expect, before, after, doc, gold=None, *, code_path="m.py", doc_path="docs/x.md", extra=None):
    files_before = {code_path: before, doc_path: doc, **(extra or {})}
    files_after = {**files_before, code_path: after}
    CASES.append(dict(name=name, truth=truth, expect=expect, before=files_before, after=files_after, doc_path=doc_path, gold=gold))


def fn(sig, body="    return None\n"):
    return f"def {sig}:\n{body}"


def H(text, title="X"):
    return f"# {title}\n\n{text}\n"


# A. Declared defaults in a signature: every literal type, fixed in the doc's style.
for name, old, new, doc_old, doc_new in [
    ("int", "30", "60", "30", "60"),
    ("float", "0.5", "0.75", "0.5", "0.75"),
    ("float-short", "0.5", "0.25", ".5", "0.25"),
    ("exp", "1e-6", "1e-9", "1e-6", "1e-9"),
    ("negative", "-1", "0", "-1", "0"),
    ("bool", "True", "False", "True", "False"),
    ("none", "None", "100", "None", "100"),
    ("str-single", "'utf-8'", "'latin-1'", "'utf-8'", "'latin-1'"),
    ("str-double-doc", "'utf-8'", "'latin-1'", '"utf-8"', '"latin-1"'),
    ("tuple", "(1, 2)", "(1, 3)", "(1, 2)", "(1, 3)"),
    ("unicode", "'€'", "'£'", "'€'", "'£'"),
]:
    case(f"sig-default-{name}", "stale", "fixed", fn(f"f(a, b={old})"), fn(f"f(a, b={new})"),
         H(f"Signature: `f(a, b={doc_old})`."), H(f"Signature: `f(a, b={doc_new})`."))
case("sig-default-spaced", "stale", "fixed", fn("f(a, b=1)"), fn("f(a, b=2)"),
     H("Signature: `f(a, b = 1)`."), H("Signature: `f(a, b = 2)`."))
case("call-default", "stale", "fixed", fn("f(a, b=1)"), fn("f(a, b=2)"),
     H("Default: `f(x, b=1)`."), H("Default: `f(x, b=2)`."))
case("two-defaults-one-changed", "stale", "fixed", fn("f(a=1, b=2)"), fn("f(a=1, b=3)"),
     H("Signature: `f(a=1, b=2)`."), H("Signature: `f(a=1, b=3)`."))

# B. Signature shape changes (declared) rewrite the whole signature.
for name, old, new in [("add-param", "f(a)", "f(a, b=1)"), ("drop-param", "f(a, b=1)", "f(a)"),
                       ("rename-param", "f(user)", "f(account)"), ("kwonly", "f(a, b=1)", "f(a, *, b=1)"),
                       ("type-hint", "f(a: str)", "f(a: int)"), ("varargs", "f(a)", "f(a, *rest)")]:
    case(f"sig-{name}", "stale", "fixed", fn(old), fn(new), H(f"Signature: `{old}`."), H(f"Signature: `{new}`."))

# C. Config constants and keys, declared.
for name, old, new, doc_old, doc_new in [
    ("int", "100", "250", "100", "250"),
    ("str", "'us'", "'eu'", "'us'", "'eu'"),
    ("str-double-doc", "'us'", "'eu'", '"us"', '"eu"'),
    ("symbol", "'::'", "'->'", "'::'", "'->'"),
    ("raw-regex", r"r'^\d{4}$'", r"r'^\d{6}$'", r"r'^\d{4}$'", r"r'^\d{6}$'"),
    ("float", "0.15", "0.2", "0.15", "0.2"),
    ("bool", "False", "True", "False", "True"),
]:
    case(f"config-{name}", "stale", "fixed", f"LIMIT = {old}\n", f"LIMIT = {new}\n",
         H(f"Default configuration: `LIMIT = {doc_old}`."), H(f"Default configuration: `LIMIT = {doc_new}`."))
case("config-compact", "stale", "fixed", "LIMIT = 1\n", "LIMIT = 2\n",
     H("Default configuration: `LIMIT=1`."), H("Default configuration: `LIMIT=2`."))
case("toml-key", "stale", "fixed", "[server]\nport = 8080\n", "[server]\nport = 9090\n",
     H("Default configuration: `server.port = 8080`."), H("Default configuration: `server.port = 9090`."), code_path="app.toml")
case("toml-bool", "stale", "fixed", "[features]\nbeta = false\n", "[features]\nbeta = true\n",
     H("Default configuration: `features.beta = false`."), H("Default configuration: `features.beta = true`."), code_path="app.toml")
case("dataclass-field", "stale", "fixed",
     "from dataclasses import dataclass\n\n@dataclass\nclass Policy:\n    attempts: int = 3\n",
     "from dataclasses import dataclass\n\n@dataclass\nclass Policy:\n    attempts: int = 5\n",
     H("The Policy class.\n\nDefault: `attempts=3`."), H("The Policy class.\n\nDefault: `attempts=5`."))
case("argparse-flag", "stale", "fixed",
     'import argparse\np = argparse.ArgumentParser()\np.add_argument("--port", type=int, default=8000)\n',
     'import argparse\np = argparse.ArgumentParser()\np.add_argument("--port", type=int, default=9000)\n',
     H("Default: `--port 8000`."), H("Default: `--port 9000`."), code_path="cli.py")

# D. Python code blocks.
case("block-labelled", "stale", "fixed", fn("compress(d, level=6)"), fn("compress(d, level=9)"),
     H("Defaults:\n\n```python\ncompress(d, level=6)\n```"), H("Defaults:\n\n```python\ncompress(d, level=9)\n```"))
case("block-config", "stale", "fixed", "MAX = 1\nMIN = 0\n", "MAX = 2\nMIN = 0\n",
     H("Default configuration:\n\n```python\nMAX = 1\nMIN = 0\n```"), H("Default configuration:\n\n```python\nMAX = 2\nMIN = 0\n```"))
case("block-unlabelled", "stale", "review", fn("compress(d, level=6)"), fn("compress(d, level=9)"),
     H("```python\ncompress(d, level=6)\n```"))
case("block-example-override", "ok", "review", fn("compress(d, level=6)"), fn("compress(d, level=9)"),
     H("Example:\n\n```python\ncompress(d, level=6)\n```"))
case("block-bash", "ok", "review", fn("compress(d, level=6)"), fn("compress(d, level=9)"),
     H("Defaults:\n\n```bash\ncompress --level 9\n```"))

# E. reStructuredText.
case("rst-signature", "stale", "fixed", fn("f(a, b=1)"), fn("f(a, b=2)"),
     "API\n===\n\nSignature: ``f(a, b=1)``.\n", "API\n===\n\nSignature: ``f(a, b=2)``.\n", doc_path="docs/x.rst")
case("rst-literal-block-untouched", "stale", "fixed", fn("f(a, b=1)"), fn("f(a, b=2)"),
     "API\n===\n\nSignature: ``f(a, b=1)``.\n\nExample::\n\n    f(a, b=1)\n",
     "API\n===\n\nSignature: ``f(a, b=2)``.\n\nExample::\n\n    f(a, b=1)\n", doc_path="docs/x.rst")

# F. Must stay review: true drift DocMend cannot prove a fix for.
for name, before, after, doc in [
    ("prose-number", fn("poll(job, interval=10)"), fn("poll(job, interval=2)"), "`poll` checks every 10 seconds."),
    ("prose-word", fn("poll(job, interval=10)"), fn("poll(job, interval=2)"), "`poll` checks every ten seconds."),
    ("behaviour", fn("send(m)", "    for _ in range(3):\n        pass\n"), fn("send(m)", "    for _ in range(5):\n        pass\n"), "`send` retries three times."),
    ("return-type", fn("total(c) -> int"), fn("total(c) -> float"), "`total` returns an `int`."),
    ("made-async", fn("load(k)"), "async " + fn("load(k)"), "`load` is a blocking call."),
    ("removed", fn("legacy_export(r)") + "\n" + fn("keep()"), fn("keep()"), "Use `legacy_export(rows)` for CSV."),
    ("renamed-prose", fn("ship_order(o)", "    return o\n"), fn("dispatch_order(o)", "    return o\n"), "Call `ship_order` to ship."),
    ("base-class", "class Cart(list):\n    pass\n", "class Cart(dict):\n    pass\n", "`Cart` is a list."),
    ("route", "@app.get('/orders')\ndef list_orders():\n    return []\n", "@app.get('/v2/orders')\ndef list_orders():\n    return []\n", "Use `GET /orders`."),
    ("cli-name", "@cli.command('sync-stock')\ndef sync_stock():\n    pass\n", "@cli.command('stock-sync')\ndef sync_stock():\n    pass\n", "Run `shop sync-stock`."),
    ("toml-prose", "[server]\nport = 8080\n", "[server]\nport = 9090\n", "The server listens on `server.port`, 8080 by default."),
]:
    case(f"review-{name}", "stale", "review", before, after, H(doc), code_path="app.toml" if name.startswith("toml") else "m.py")

# G. Doc is still right but linked code changed: review is allowed, editing is not.
for name, before, after, doc in [
    ("history", fn("backoff(n, base=2)"), fn("backoff(n, base=3)"), "History: the previous default was `backoff(n, base=2)`."),
    ("example", fn("resize(img, width=800)"), fn("resize(img, width=1024)"), "Example: call `resize(img, width=800)` to override the width."),
    ("refactor", fn("double(x)", "    return x + x\n"), fn("double(x)", "    return 2 * x\n"), "`double(x)` returns twice its input."),
    ("migration-heading", fn("f(a, b=1)"), fn("f(a, b=2)"), "Signature: `f(a, b=1)`."),
]:
    case(f"ok-{name}", "ok", "review", before, after, H(doc, "Migration notes" if name == "migration-heading" else "X"))

# H. Quiet: the doc is already right or the change cannot affect it.
case("quiet-already-updated", "ok", "quiet", fn("f(a, b=1)"), fn("f(a, b=2)"), H("Signature: `f(a, b=2)`."))
case("quiet-comment-only", "ok", "quiet", fn("f(a)", "    # one\n    return a\n"), fn("f(a)", "    # two\n    return a\n"), H("`f(a)` returns `a`."))
case("quiet-docstring-only", "ok", "quiet", fn("f(a)", '    """Old."""\n    return a\n'), fn("f(a)", '    """New."""\n    return a\n'), H("`f(a)` returns `a`."))
case("quiet-whitespace", "ok", "quiet", fn("f(a)", "    return a\n"), fn("f(a)", "    return  a\n"), H("`f(a)` returns `a`."))
case("quiet-unrelated-code", "ok", "quiet", fn("g(a, b=1)") + "\n" + fn("f(a)"), fn("g(a, b=2)") + "\n" + fn("f(a)"), H("Signature: `f(a)`."))
case("quiet-common-word", "ok", "quiet", fn("run(a=1)"), fn("run(a=2)"), H("Run the tests before you ship."))
for i, word in enumerate(["format_price", "slugify", "is_vip", "parse_date", "hash_password", "chunk", "clamp",
                          "pluralize", "mask_card", "weight_kg", "checksum", "rate_limit", "barcode", "audit_line",
                          "greet_user", "tax_for", "round_cents", "to_cents", "from_cents", "sku_ok"]):
    case(f"quiet-control-{word}", "ok", "quiet", fn(f"{word}(v, k=1)") + "\n" + fn("other(x=1)"),
         fn(f"{word}(v, k=1)") + "\n" + fn("other(x=2)"), H(f"Signature: `{word}(v, k=1)`."))

# I. Safety: never guess across ambiguity or several changes at once.
case("ambiguous-duplicate", "stale", "review", fn("f(a, b=1)") + "\n" + fn("f(a, b=1)"), fn("f(a, b=2)") + "\n" + fn("f(a, b=1)"),
     H("Signature: `f(a, b=1)`."))
case("two-units-one-section", "stale", "review", fn("f(a, b=1)") + "\n" + fn("g(c=1)"), fn("f(a, b=2)") + "\n" + fn("g(c=2)"),
     H("Signature: `f(a, b=1)` and `g(c=1)`."))
case("bool-not-number", "ok", "review", "FLAG = True\n", "FLAG = False\n", H("Default configuration: `FLAG = 1` means on."))
case("pipes-and-html-in-doc", "stale", "fixed", fn("f(a, b='x|y')"), fn("f(a, b='x|z')"),
     H("Signature: `f(a, b='x|y')` <b>bold</b>.", "Weird | heading <i>"), H("Signature: `f(a, b='x|z')` <b>bold</b>.", "Weird | heading <i>"))

# J. Real-world phrasing: "`name` defaults to `value`" (mined from click/typer/httpx/requests docs).
FETCH = "fetch(url, timeout={})"
case("phrase-defaults-to", "stale", "fixed", fn(FETCH.format(30)), fn(FETCH.format(60)),
     H("`fetch` sends a request. `timeout` defaults to `30`.", "fetch"), H("`fetch` sends a request. `timeout` defaults to `60`.", "fetch"))
case("phrase-default-is", "stale", "fixed", fn(FETCH.format(30)), fn(FETCH.format(60)),
     H("For `fetch`, the default value is: `timeout` default is `30` seconds."), H("For `fetch`, the default value is: `timeout` default is `60` seconds."))
case("phrase-paren-default", "stale", "fixed", fn(FETCH.format(30)), fn(FETCH.format(60)),
     H("- `timeout` (default: `30`) for `fetch` calls."), H("- `timeout` (default: `60`) for `fetch` calls."))
case("phrase-quoted-value", "stale", "fixed", fn("read(path, encoding='utf-8')"), fn("read(path, encoding='latin-1')"),
     H("`read` opens a file; `encoding` defaults to `\"utf-8\"`."), H("`read` opens a file; `encoding` defaults to `\"latin-1\"`."))
case("phrase-unquoted-value", "stale", "fixed", fn("read(path, encoding='utf-8')"), fn("read(path, encoding='latin-1')"),
     H("`read` opens a file; `encoding` defaults to `utf-8`."), H("`read` opens a file; `encoding` defaults to `latin-1`."))
case("phrase-config", "stale", "fixed", "MAX_ITEMS = 100\n", "MAX_ITEMS = 250\n",
     H("`MAX_ITEMS` defaults to `100`."), H("`MAX_ITEMS` defaults to `250`."))
case("phrase-flag", "stale", "fixed", fn("fetch(url, retries=3)"), fn("fetch(url, retries=5)"),
     H("`fetch`: `--retries` defaults to `3`."), H("`fetch`: `--retries` defaults to `5`."))
# ...and the cases it must leave alone.
case("phrase-other-function", "ok", "review", fn(FETCH.format(30)) + "\n" + fn("poll(job, timeout=30)"), fn(FETCH.format(60)) + "\n" + fn("poll(job, timeout=30)"),
     H("Use `fetch` for pages.\n\nFor `poll`, `timeout` defaults to `30`.", "Client"))
case("phrase-was", "ok", "review", fn(FETCH.format(30)), fn(FETCH.format(60)),
     H("`fetch` changed: `timeout` previously defaulted to `30`.", "fetch"))
case("phrase-history-line", "ok", "review", fn(FETCH.format(30)), fn(FETCH.format(60)),
     H("In the old release, for `fetch`, `timeout` defaults to `30`.", "fetch"))
case("phrase-value-differs", "stale", "review", fn(FETCH.format(30)), fn(FETCH.format(60)),
     H("`fetch`: `timeout` defaults to `45`.", "fetch"))
case("phrase-no-backticks", "stale", "review", fn(FETCH.format(30)), fn(FETCH.format(60)),
     H("For fetch, timeout defaults to 30.", "fetch"))
case("phrase-cli-help-output", "stale", "review", fn("hello(name='World')"), fn("hello(name='Earth')"),
     H("`hello` prints:\n\n```\n--name TEXT  [default: World]\n```", "hello"))
