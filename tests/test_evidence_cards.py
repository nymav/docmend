import json
import unittest

from docmend.pipeline import analyze_files
from docmend.reporting import markdown
from docmend.sarif import sarif

CODE = 'import os\n\n\ndef fetch(url, timeout={}):\n    return url\n'
DOC = '# API\n\nIntro line.\n\nSignature: `fetch(url, timeout=30)`.\n'


def run(doc=DOC):
    b = {'m.py': CODE.format(30), 'docs/api.md': doc}
    return analyze_files(b, {**b, 'm.py': CODE.format(60)}, base='a' * 40, head='b' * 40)[0]


class EvidenceCardTests(unittest.TestCase):
    def test_card_points_at_exact_lines(self):
        c = run().findings[0].card
        self.assertEqual(c['doc'], {'path': 'docs/api.md', 'lines': [1, 5]})
        self.assertEqual(c['declared_facts'], [{'line': 5, 'text': 'fetch(url, timeout=30)'}])
        ch = c['changes'][0]
        self.assertEqual((ch['unit'], ch['change']), ('m.py::fetch', 'contract'))
        self.assertEqual(ch['before'], {'path': 'm.py', 'lines': [4, 5], 'kind': 'function', 'states': 'fetch(url, timeout=30)'})
        self.assertEqual(ch['after']['states'], 'fetch(url, timeout=60)')
        self.assertEqual(c['edit'], {'mode': 'safe', 'removed': ['Signature: `fetch(url, timeout=30)`.'], 'added': ['Signature: `fetch(url, timeout=60)`.']})

    def test_review_card_says_no_declared_fact(self):
        r = run('# API\n\n`fetch` waits thirty seconds.\n')
        self.assertEqual(r.findings[0].card['declared_facts'], [])
        self.assertIn('no declared Signature/Default fact', markdown(r))

    def test_summary_and_sarif(self):
        r = run()
        md = markdown(r)
        self.assertIn('### Evidence', md)
        self.assertIn('<code>aaaaaaaaaaaa</code>', md)
        self.assertIn('lines 4–5', md)
        res = sarif(r)['runs'][0]['results'][0]
        self.assertEqual(res['relatedLocations'][0]['physicalLocation']['region'], {'startLine': 4, 'endLine': 5})
        self.assertEqual(res['properties']['card']['doc']['lines'], [1, 5])

    def test_hostile_doc_text_is_escaped(self):
        r = run('# API <script>\n\nSignature: `fetch(url, timeout=30)`. </details><img src=x onerror=alert(1)>\n')
        md = markdown(r).split('### Evidence', 1)[1]
        self.assertNotIn('<script>', md)
        self.assertNotIn('<img', md)
        self.assertEqual(md.count('<details>'), md.count('</details>'))


if __name__ == '__main__':
    unittest.main()
