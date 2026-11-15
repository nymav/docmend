import unittest

from docmend.diagnosis import _same_value, _in_doc_style, _normal_signature
from docmend.pipeline import analyze_files


def fix(code_before, code_after, doc):
    b = {'m.py': code_before, 'docs/m.md': '# M\n\n' + doc + '\n'}
    r, _ = analyze_files(b, {**b, 'm.py': code_after})
    return r.edits[0].after if r.edits else None


class SameValueTests(unittest.TestCase):
    def test_meaning(self):
        self.assertTrue(_same_value('1e-6', '1e-06'))
        self.assertTrue(_same_value('0.5', '.5'))
        self.assertTrue(_same_value('"a"', "'a'"))
        self.assertTrue(_same_value('30', '30.0'))
        self.assertFalse(_same_value('True', '1'))
        self.assertFalse(_same_value('None', '0'))
        self.assertFalse(_same_value("'30'", '30'))

    def test_style(self):
        self.assertEqual(_in_doc_style("'b'", '"a"'), '"b"')
        self.assertEqual(_in_doc_style('1e-09', '1e-6'), '1e-9')
        self.assertEqual(_in_doc_style('60', '30'), '60')
        self.assertEqual(_in_doc_style("'^\\\\d{6}$'", "r'^\\d{4}$'"), "r'^\\d{6}$'")
        self.assertEqual(_in_doc_style("'a\\\\'", "r'b'"), "'a\\\\'")

    def test_signature(self):
        self.assertEqual(_normal_signature('f(a, b = "x")'), _normal_signature("f(a, b='x')"))


class RepairTests(unittest.TestCase):
    def test_exponent_default(self):
        out = fix('def close(a, eps=1e-6):\n    pass\n', 'def close(a, eps=1e-9):\n    pass\n', 'Signature: `close(a, eps=1e-6)`.')
        self.assertIn('`close(a, eps=1e-9)`', out)

    def test_call_keeps_doc_style(self):
        out = fix('def read(p, enc="utf-8", n=1e-6):\n    pass\n', 'def read(p, enc="latin-1", n=1e-9):\n    pass\n',
                  'Default: `read(p, enc = "utf-8", n=1e-6)`.')
        self.assertIn('`read(p, enc = "latin-1", n=1e-9)`', out)

    def test_config_double_quotes_and_spacing(self):
        out = fix("REGION = 'us-east-1'\n", "REGION = 'eu-west-1'\n", 'Default configuration: `REGION  =  "us-east-1"`.')
        self.assertIn('`REGION  =  "eu-west-1"`', out)

    def test_bool_is_not_number(self):
        self.assertIsNone(fix('FLAG = True\n', 'FLAG = False\n', 'Default configuration: `FLAG = 1`.'))

    def test_spaced_signature(self):
        out = fix('def f(a, b=1):\n    pass\n', 'def f(a, b=2):\n    pass\n', 'Signature: `f(a, b = 1)`.')
        self.assertIn('`f(a, b = 2)`', out)


if __name__ == '__main__':
    unittest.main()
