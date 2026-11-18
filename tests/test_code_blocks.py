import unittest

from docmend.pipeline import analyze_files

FN_B = 'def compress(data, level=6):\n    return data\n'
FN_A = FN_B.replace('level=6', 'level=9')


def run(doc, before=FN_B, after=FN_A, heading='Compress'):
    b = {'m.py': before, 'docs/m.md': f'# {heading}\n\n{doc}'}
    r, _ = analyze_files(b, {**b, 'm.py': after})
    return r


class CodeBlockTests(unittest.TestCase):
    def test_labelled_block_is_repaired(self):
        r = run('`compress` defaults:\n\n```python\ncompress(data, level=6)\n```\n')
        self.assertEqual(r.findings[0].status, 'stale')
        self.assertIn('```python\ncompress(data, level=9)\n```', r.edits[0].after)

    def test_signature_block(self):
        r = run('Signature:\n\n```py\ndef compress(data, level = 6): ...\n```\n')
        self.assertFalse(r.edits)  # a def line is not a call or a bare signature; left for review

    def test_config_block(self):
        r = run('Default configuration:\n\n```python\nMAX_ITEMS = 100\nREGION = "us"\n```\n',
                'MAX_ITEMS = 100\nREGION = "us"\n', 'MAX_ITEMS = 250\nREGION = "us"\n')
        self.assertIn('MAX_ITEMS = 250\nREGION = "us"', r.edits[0].after)

    def test_unlabelled_example_and_commented_blocks_are_left_alone(self):
        for doc in ['```python\ncompress(data, level=6)\n```\n',
                    'Example:\n\n```python\ncompress(data, level=6)\n```\n',
                    'Defaults:\n\n```python\ncompress(data, level=6)  # override\n```\n',
                    'Defaults:\n\n```bash\ncompress(data, level=6)\n```\n']:
            with self.subTest(doc=doc):
                self.assertFalse(run(doc).edits)

    def test_history_heading_is_left_alone(self):
        self.assertFalse(run('Defaults:\n\n```python\ncompress(data, level=6)\n```\n', heading='Migration notes').edits)

    def test_fence_lines_are_kept(self):
        r = run('Defaults:\n\n~~~~python\ncompress(data, level=6)\n~~~~\n')
        self.assertIn('~~~~python\ncompress(data, level=9)\n~~~~', r.edits[0].after)


if __name__ == '__main__':
    unittest.main()
