import unittest

from docmend import jsparse
from docmend.codeparse import parse_code
from docmend.models import DocMendError
from docmend.pipeline import analyze_files
from docmend.repair import patched_files

TS = """// client
export async function fetchUser(id: string, timeout = 30): Promise<User> {
  return get(id, timeout);
}
export const retry = (n, delay = 100) => n * delay;
export class Client extends Base {
  retries: number = 3;
  send(body: string) { return body; }
}
export const MAX_SIZE = 10;
function helper() {}
"""
DOC = "# API\n\nSignature: `fetchUser(id: string, timeout = 30)`.\n\n## Other\nUntouched.\n"


@unittest.skipUnless(jsparse.available(), "docmend[js] extra not installed")
class JsParseTests(unittest.TestCase):
    def test_units_and_facts(self):
        u = parse_code({"src/client.ts": TS})
        self.assertEqual(sorted(u), sorted(f"src/client.ts::{n}" for n in
                         ["fetchUser", "retry", "Client", "Client.send", "MAX_SIZE", "helper"]))
        f = u["src/client.ts::fetchUser"]
        self.assertEqual(f.facts["signature"], "fetchUser(id: string, timeout = 30)")
        self.assertEqual(f.facts["params"], {"id": None, "timeout": "30"})
        self.assertEqual((f.line, f.end_line), (2, 4))
        self.assertEqual(u["src/client.ts::retry"].facts["params"], {"n": None, "delay": "100"})
        self.assertEqual(u["src/client.ts::Client"].facts["fields"]["retries"], {"annotation": "number", "value": "3"})
        self.assertEqual(u["src/client.ts::MAX_SIZE"].facts["value"], "10")

    def test_comments_and_spacing_do_not_change_behaviour(self):
        a = parse_code({"a.js": "function f(x) { return x + 1 }\n"})["a.js::f"]
        b = parse_code({"a.js": "function f(x) {\n  // add one\n  return x+1\n}\n"})["a.js::f"]
        self.assertEqual((a.contract, a.semantic), (b.contract, b.semantic))

    def test_syntax_error_is_reported(self):
        with self.assertRaises(DocMendError):
            parse_code({"a.js": "function f( {"})

    def test_signature_change_gets_safe_repair(self):
        before = {"src/client.ts": TS, "docs/api.md": DOC}
        after = {**before, "src/client.ts": TS.replace("timeout = 30", "timeout = 60")}
        report, _ = analyze_files(before, after)
        self.assertEqual(report.findings[0].status, "stale")
        text = patched_files(after, report.edits)["docs/api.md"]
        self.assertIn("`fetchUser(id: string, timeout = 60)`", text)
        self.assertTrue(text.endswith("## Other\nUntouched.\n"))


if __name__ == "__main__":
    unittest.main()
