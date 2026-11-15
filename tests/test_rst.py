from dataclasses import replace
import unittest

from docmend.docparse import parse_docs, rst_headings
from docmend.models import DocMendError
from docmend.pipeline import analyze_files
from docmend.repair import patched_files, validate_edit

DOC = """=====
 API
=====

Intro text.

Fetching
--------

Signature: ``fetch(url, timeout=30)``.

Example::

    Heading inside literal
    ----------------------

.. code-block:: python

    fetch(url, timeout=30)

Other
-----

Untouched.
"""
BEFORE = {'api.py': 'def fetch(url, timeout=30):\n    return url\n', 'docs/api.rst': DOC}
AFTER = {**BEFORE, 'api.py': 'def fetch(url, timeout=60):\n    return url\n'}


class RstParseTests(unittest.TestCase):
    def test_levels_follow_first_use_and_skip_literals(self):
        self.assertEqual([(t, lv) for _, t, lv in rst_headings(DOC)], [('API', 1), ('Fetching', 2), ('Other', 2)])

    def test_sections_partition_file(self):
        s = list(parse_docs({'docs/api.rst': DOC}).values())
        self.assertEqual([x.heading for x in s], ['API', 'API > Fetching', 'API > Other'])
        self.assertEqual(''.join(x.text for x in s), DOC)

    def test_short_underline_is_not_heading(self):
        self.assertEqual(rst_headings('Long title\n---\n'), [])


class RstPipelineTests(unittest.TestCase):
    def setUp(self):
        self.report, _ = analyze_files(BEFORE, AFTER)

    def test_inline_literal_gets_safe_repair_only_there(self):
        self.assertEqual(len(self.report.edits), 1)
        text = patched_files(AFTER, self.report.edits)['docs/api.rst']
        self.assertIn('Signature: ``fetch(url, timeout=60)``.', text)
        self.assertIn('    fetch(url, timeout=30)\n', text)
        self.assertTrue(text.endswith('Other\n-----\n\nUntouched.\n'))

    def test_structure_checks(self):
        e = self.report.edits[0]
        cases = [
            replace(e, after=e.after.replace('--------', '========')),
            replace(e, after=e.after.replace('Example::', 'Example:')),
            replace(e, after=e.after.replace('.. code-block:: python', '.. code-block:: js')),
            replace(e, after=e.after + 'See `docs <https://bad.invalid>`_.\n'),
        ]
        for bad in cases:
            with self.subTest(after=bad.after):
                with self.assertRaises(DocMendError):
                    validate_edit(bad)


if __name__ == '__main__':
    unittest.main()
