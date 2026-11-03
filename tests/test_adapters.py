import unittest
from docmend.adapters import parse_json
from docmend.models import DocMendError
from docmend.pipeline import analyze_files

class AdapterTests(unittest.TestCase):
    def test_spans_pointers_and_contracts(self):
        text='{\n "http": {"timeout": 30},\n "items": [1, 2], "a/b": true\n}'
        units=parse_json('settings.json',text)
        self.assertEqual(units[0].name,'http.timeout')
        self.assertEqual((units[0].line,units[0].end_line),(2,2))
        self.assertEqual(units[0].source,'30')
        self.assertEqual(units[-1].facts['pointer'],'/a~1b')
    def test_config_drift_and_format_only(self):
        before={'settings.json':'{"timeout":30}','guide.md':'# Defaults\nDefault: `timeout=30`.\n'}
        report,_=analyze_files(before,{**before,'settings.json':'{"timeout":60}'})
        self.assertEqual(report.findings[0].status,'stale')
        self.assertIn('timeout=60',report.edits[0].after)
        report,_=analyze_files(before,{**before,'settings.json':'{ "timeout" : 30 }'})
        self.assertEqual(report.changes,[])
    def test_reject_ambiguous_and_malformed(self):
        for text in ('{"a":1,"a":2}','{"a":NaN}','{"a":1} trailing','{"a":}'):
            with self.assertRaises(DocMendError):parse_json('a.json',text)
    def test_unknown_changed_language_warns(self):
        report,_=analyze_files({'api.ts':'old'},{'api.ts':'new'})
        self.assertTrue(any('unsupported changed source' in w for w in report.warnings))
    def test_repository_reports_default_excluded_languages(self):
        from pathlib import Path
        import tempfile
        from test_core import fixture,git
        from docmend.gitstore import GitStore
        from docmend.pipeline import analyze_repository
        with tempfile.TemporaryDirectory() as td:
            base,_=fixture(td)
            (Path(td)/'api.ts').write_text('export const timeout = 60;')
            git(td,'add','api.ts');git(td,'commit','-m','typescript source')
            report,_,_=analyze_repository(GitStore(Path(td)),base,'HEAD')
            self.assertTrue(any('api.ts' in w and 'coverage is incomplete' in w for w in report.warnings))
