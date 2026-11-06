import unittest

from docmend.codeparse import parse_code
from docmend.models import DocMendError
from docmend.pipeline import analyze_files
from docmend.reporting import summary


class DuplicateDefinitionTests(unittest.TestCase):
    def test_parser_stays_strict_by_default(self):
        with self.assertRaises(DocMendError):
            parse_code({'a.py': 'X=1\nX=2\n'})

    def test_constant_reassignment_keeps_all_evidence_without_fix(self):
        before = {'a.py': 'X=1\nX=2\n', 'guide.md': '# Config\nDefault: `X=2`.\n'}
        after = {**before, 'a.py': 'X=1\nX=3\n'}
        report, graph = analyze_files(before, after)
        self.assertEqual(report.findings[0].status, 'review')
        self.assertFalse(report.edits)
        self.assertGreater(summary(report)['coverage_gaps'], 0)
        unit = graph['units'][0]
        self.assertEqual(unit['facts']['definition_lines'], [1, 2])
        self.assertIn('X=1', unit['source'])
        self.assertIn('X=3', unit['source'])

    def test_change_to_first_definition_is_not_lost(self):
        before = {'a.py': 'X=1\nX=2\n'}
        report, _ = analyze_files(before, {'a.py': 'X=9\nX=2\n'})
        self.assertEqual(len(report.changes), 1)

    def test_repeated_class_unique_methods_are_ambiguous_too(self):
        units = parse_code({'a.py': 'class Model:\n def load(self): pass\nclass Model:\n def save(self): pass\n'}, review_duplicates=True)
        self.assertEqual({u.kind for u in units.values()}, {'ambiguous'})
        self.assertEqual(len(units), 3)

    def test_duplicate_to_single_binding_still_requires_review(self):
        before = {'a.py': 'def fetch(timeout=1): pass\ndef fetch(timeout=2): pass\n',
                  'guide.md': '# API\nSignature: `fetch(timeout=2)`.\n'}
        report, _ = analyze_files(before, {**before, 'a.py': 'def fetch(timeout=3): pass\n'})
        self.assertEqual(report.findings[0].status, 'review')
        self.assertFalse(report.edits)

    def test_unrelated_units_still_get_checked(self):
        before = {'a.py': 'X=1\nX=2\nLIMIT=10\n', 'guide.md': '# Defaults\nDefault: `LIMIT=10`.\n'}
        report, _ = analyze_files(before, {**before, 'a.py': 'X=1\nX=2\nLIMIT=20\n'})
        self.assertEqual(len(report.edits), 1)
        self.assertIn('LIMIT=20', report.edits[0].after)

    def test_ambiguous_units_never_call_provider(self):
        class RejectProvider:
            def json(self, *args):
                raise AssertionError('Ambiguous binding must not be delegated to a model')
        before = {'a.py': 'X=1\nX=2\n', 'guide.md': '# Config\nDefault: `X=2`.\n'}
        report, _ = analyze_files(before, {**before, 'a.py': 'X=1\nX=3\n'}, provider=RejectProvider())
        self.assertEqual(report.findings[0].status, 'review')
        self.assertFalse(report.edits)

    def test_invalid_python_is_still_an_error(self):
        with self.assertRaises(DocMendError):
            analyze_files({'a.py': 'def broken('}, {'a.py': 'def broken('})

    def test_strict_cli_gate_fails_but_report_only_writes_evidence(self):
        from pathlib import Path
        import tempfile
        from test_core import fixture, git
        from docmend.cli import main
        with tempfile.TemporaryDirectory() as td:
            fixture(td)
            (Path(td) / 'duplicate.py').write_text('X=1\nX=2\n')
            git(td, 'add', 'duplicate.py')
            git(td, 'commit', '-m', 'reassigned constant')
            args = ['check', '--repo', td, '--base', 'HEAD', '--head', 'HEAD', '--output', 'report']
            self.assertEqual(main(args + ['--fail-on', 'review']), 2)
            self.assertEqual(main(args + ['--fail-on', 'never']), 0)
            self.assertTrue((Path(td) / 'report' / 'report.json').is_file())
