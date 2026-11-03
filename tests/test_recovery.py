import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from docmend.models import Edit, DocMendError, digest
from docmend.repair import apply_local
from docmend.recovery import recover_local, JOURNAL


def edits():
    return [Edit(p,p,0,2,'# Title\nOld.\n','# Title\nNew.\n',digest('# Title\nOld.\n'),'safe','test') for p in ('a.md','b.md')]

class RecoveryTests(unittest.TestCase):
    def prepare(self,root):
        for e in edits():(root/e.path).write_text(e.before)
    def test_multifile_write_failure_rolls_back(self):
        from docmend.repair import atomic_write
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.prepare(root)
            def fail(path,text):
                if path.name=='b.md' and 'New.' in text:raise OSError('injected')
                atomic_write(path,text)
            with patch('docmend.repair.atomic_write',side_effect=fail):
                with self.assertRaises(OSError):apply_local(root,edits())
            self.assertTrue(all((root/e.path).read_text()==e.before for e in edits()))
            self.assertFalse((root/JOURNAL).exists())
    def test_process_crash_and_explicit_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.prepare(root)
            script='''import os,json
from pathlib import Path
from unittest.mock import patch
from docmend.repair import apply_local,atomic_write
from docmend.models import Edit
items=[Edit(**e) for e in json.loads(os.environ['CRASH_EDITS'])]
def crash(path,text):
 atomic_write(path,text)
 os._exit(91)
with patch('docmend.repair.atomic_write',side_effect=crash):apply_local(Path(os.environ['CRASH_ROOT']),items)
'''
            from dataclasses import asdict
            env={**os.environ,'CRASH_ROOT':td,'CRASH_EDITS':json.dumps([asdict(e) for e in edits()])}
            result=subprocess.run([sys.executable,'-c',script],env=env)
            self.assertEqual(result.returncode,91)
            self.assertTrue((root/JOURNAL).exists())
            self.assertIn('New.',(root/'a.md').read_text())
            with self.assertRaises(DocMendError):recover_local(root)
            with self.assertRaises(DocMendError):apply_local(root,edits())
            (root/'b.md').write_text('User edit')
            with self.assertRaises(DocMendError):recover_local(root,confirm_no_active_writer=True)
            self.assertIn('New.',(root/'a.md').read_text()) # preflight prevents partial rollback
            (root/'b.md').write_text(edits()[1].before)
            self.assertEqual(recover_local(root,confirm_no_active_writer=True),['a.md','b.md'])
            self.assertTrue(all((root/e.path).read_text()==e.before for e in edits()))
    def test_error_after_rename_still_rolls_back(self):
        from docmend.repair import atomic_write
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.prepare(root)
            def fail(path,text):
                atomic_write(path,text)
                if path.name=='a.md' and 'New.' in text:raise OSError('after rename')
            with patch('docmend.repair.atomic_write',side_effect=fail):
                with self.assertRaises(OSError):apply_local(root,edits())
            self.assertEqual((root/'a.md').read_text(),edits()[0].before)
            self.assertFalse((root/JOURNAL).exists())
