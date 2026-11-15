import json
import unittest
from unittest.mock import patch

from docmend.models import REASON_CODES
from docmend.pipeline import analyze_files
from docmend.sarif import sarif


def codes(before, after, doc):
    b = {'m.py': before, 'docs/m.md': '# M\n\n' + doc + '\n'}
    r, _ = analyze_files(b, {**b, 'm.py': after})
    return r, r.findings[0].codes


F = 'def fetch(url, timeout={}):\n    return url\n'


class ReasonCodeTests(unittest.TestCase):
    def test_fixed(self):
        _, c = codes(F.format(30), F.format(60), 'Signature: `fetch(url, timeout=30)`.')
        self.assertEqual(c, ['fixed-declared-fact', 'contract-changed'])

    def test_prose_only(self):
        _, c = codes(F.format(30), F.format(60), '`fetch` waits 30 seconds.')
        self.assertEqual(c, ['needs-review', 'contract-changed', 'old-value-in-prose', 'no-declared-fact'])

    def test_behaviour(self):
        _, c = codes('def fetch(url):\n    return url\n', 'def fetch(url):\n    return None\n', '`fetch(url)` returns the url.')
        self.assertEqual(c, ['needs-review', 'behaviour-changed', 'no-declared-fact'])

    def test_current(self):
        _, c = codes(F.format(30), F.format(60), 'Signature: `fetch(url, timeout=60)`.')
        self.assertEqual(c[0], 'verified-current')

    def test_reverify_failed(self):
        with patch('docmend.diagnosis._verify_rewrite', return_value=False):
            _, c = codes(F.format(30), F.format(60), 'Signature: `fetch(url, timeout=30)`.')
        self.assertEqual(c[0], 'reverify-failed')

    def test_every_code_is_in_vocabulary_and_one_outcome(self):
        outcomes = {'fixed-declared-fact', 'detected-stale', 'edit-rejected', 'verified-current', 'reverify-failed',
                    'ambiguous-definition', 'model-stale', 'model-accurate', 'model-uncertain', 'low-confidence',
                    'models-disagree', 'draft-rejected', 'needs-review'}
        self.assertTrue(outcomes <= set(REASON_CODES))
        for doc in ['Signature: `fetch(url, timeout=30)`.', 'waits 30s in `fetch`', 'Signature: `fetch(url, timeout=60)`.']:
            r, c = codes(F.format(30), F.format(60), doc)
            self.assertTrue(set(c) <= set(REASON_CODES), c)
            self.assertEqual(sum(x in outcomes for x in c), 1, c)

    def test_codes_in_outputs(self):
        r, _ = codes(F.format(30), F.format(60), 'Signature: `fetch(url, timeout=30)`.')
        self.assertIn('fixed-declared-fact', json.dumps(sarif(r)))
        self.assertEqual(r.to_dict()['findings'][0]['codes'][0], 'fixed-declared-fact')


if __name__ == '__main__':
    unittest.main()
