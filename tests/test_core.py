from dataclasses import replace
import json
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from docmend.changes import classify
from docmend.codeparse import parse_code
from docmend.config import Config
from docmend.docparse import parse_docs
from docmend.gitstore import GitStore
from docmend.mapping import build_index, cosine
from docmend.models import DocMendError
from docmend.pipeline import analyze_files, analyze_repository
from docmend.repair import apply_local, patched_files, validate_edit
from docmend.reporting import save
from docmend.provider import ModelProvider
from docmend.cli import main

BEFORE={'api.py':'def fetch(url, timeout=30):\n    return url\n','docs/api.md':'# API\n\nSignature: `fetch(url, timeout=30)`.\n\n## Other\nUntouched.\n'}
AFTER={**BEFORE,'api.py':'def fetch(url, timeout=60):\n    return url\n'}
def git(root,*args):return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL).decode().strip()
def fixture(root):
    git(root,'init','-b','main');git(root,'config','user.name','Test');git(root,'config','user.email','test@example.invalid')
    for p,t in BEFORE.items():
        f=Path(root)/p;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(t)
    git(root,'add','.');git(root,'commit','-m','baseline');base=git(root,'rev-parse','HEAD')
    (Path(root)/'api.py').write_text(AFTER['api.py']);git(root,'add','api.py');git(root,'commit','-m','timeout');return base,git(root,'rev-parse','HEAD')

class ParserTests(unittest.TestCase):
    def test_python_contracts(self):
        u=parse_code({'api.py':'@app.get("/health")\ndef check(q: str="ok"):\n    return q\nLIMIT=10\nclass Settings:\n    retries: int=2\n    def run(self): return 1\n'})
        self.assertEqual(set(u),{'api.py::check','api.py::LIMIT','api.py::Settings','api.py::Settings.run'})
        self.assertIn('/health',str(u['api.py::check'].facts));self.assertIn('retries',u['api.py::Settings'].facts['fields'])
    def test_cli_decorator_names_link_to_docs(self):
        units=parse_code({'a.py':'@app.command(name="serve")\n@click.option("--port",default=8000)\ndef main(port): return port\n'})
        sections=parse_docs({'a.md':'# Usage\nRun serve with --port.\n'})
        graph=build_index(units,sections)
        self.assertEqual(len(graph['links']),1)
        self.assertIn('--port',units['a.py::main'].facts['cli_names'])

    def test_comments_whitespace_docstring_ignored(self):
        u=parse_code({**BEFORE,'api.py':'# hi\ndef fetch( url, timeout = 30 ):\n    """New docs."""\n    return url # fine\n'})
        self.assertEqual(classify(parse_code(BEFORE),u),[])
    def test_internal_refactor_conservatively_reviewed(self):
        u=parse_code({**BEFORE,'api.py':'def fetch(url, timeout=30):\n    x=url\n    return x\n'})
        self.assertEqual(classify(parse_code(BEFORE),u)[0].kind,'behaviour')
    def test_invalid_and_duplicate_definitions(self):
        for t in ['def x(', 'def x(): pass\ndef x(): pass\n']:
            with self.assertRaises(DocMendError):parse_code({'a.py':t})
    def test_toml_keys(self):self.assertEqual(parse_code({'a.toml':'[http]\ntimeout=30\n'})['a.toml::http.timeout'].facts['value'],'30')
    def test_sections_fences_duplicates_and_partition(self):
        t='# API\nA\n```python\n# fake\n```\n## Config\nB\n## Config\nC\n';s=list(parse_docs({'a.md':t}).values())
        self.assertEqual(len(s),3);self.assertEqual(''.join(x.text for x in s),t);self.assertTrue(s[2].id.endswith('-2'));self.assertEqual(s[1].heading,'API > Config')
    def test_setext_and_preamble(self):self.assertEqual(len(parse_docs({'a.md':'Intro\n\nHeading\n======\nText\n'})),2)

class PipelineTests(unittest.TestCase):
    def test_safe_edit_preserves_other_sections(self):
        r,g=analyze_files(BEFORE,AFTER);self.assertEqual(r.findings[0].status,'stale');self.assertEqual(len(r.edits),1)
        t=patched_files(AFTER,r.edits)['docs/api.md'];self.assertIn('timeout=60',t);self.assertTrue(t.endswith('## Other\nUntouched.\n'));self.assertTrue(g['fingerprint'])
    def test_explicit_override_is_not_a_default_claim(self):
        b={**BEFORE, 'docs/api.md':'# Examples\nCall `fetch(url, timeout=30)` to override the timeout.\n'}
        r,_=analyze_files(b,{**b,'api.py':AFTER['api.py']})
        self.assertFalse(r.edits)
        self.assertEqual(r.findings[0].status,'review')

    def test_parameter_rename(self):
        r,_=analyze_files(BEFORE,{**BEFORE,'api.py':'def fetch(url, wait=30):\n    return url\n'});self.assertIn('wait=30',r.edits[0].after)
    def test_updated_docs_not_autofixed(self):
        r,_=analyze_files(BEFORE,{**AFTER,'docs/api.md':BEFORE['docs/api.md'].replace('30','60')});self.assertFalse(r.edits);self.assertEqual(r.findings[0].status,'accurate')
    def test_removal_review(self):
        r,_=analyze_files(BEFORE,{**BEFORE,'api.py':''});self.assertFalse(r.edits);self.assertEqual(r.findings[0].status,'review')
    def test_simultaneous_body_and_signature_review(self):
        r,_=analyze_files(BEFORE,{**AFTER,'api.py':'def fetch(url, timeout=60):\n    return "new"\n'});self.assertFalse(r.edits)
    def test_config_repair(self):
        b={'cfg.py':'LIMIT=10\n','README.md':'# Config\nDefault: `LIMIT=10`.\n'};r,_=analyze_files(b,{**b,'cfg.py':'LIMIT=20\n'});self.assertIn('LIMIT=20',r.edits[0].after)
    def test_ambiguous_symbol_review(self):
        b={**BEFORE,'other.py':BEFORE['api.py']};r,_=analyze_files(b,{**b,'api.py':AFTER['api.py']});self.assertFalse(r.edits);self.assertIn('ambiguous',r.findings[0].reason)
    def test_unmapped_change_warns(self):
        r,_=analyze_files({'a.py':'def x(): return 1\n'},{'a.py':'def y(): return 1\n'});self.assertTrue(any('No documentation mapping' in s for s in r.warnings))
    def test_section_budget(self):
        b={**BEFORE,'extra.md':'# B\n`fetch(url, timeout=30)`\n'}
        with self.assertRaises(DocMendError):analyze_files(b,{**b,'api.py':AFTER['api.py']},cfg=Config(max_sections=1))
    def test_embedding_interface(self):
        class Fake:
            def embed(self,texts):return [[1.,0.] for _ in texts]
        g=build_index(parse_code({'a.py':'def x(): pass\n'}),parse_docs({'a.md':'# Unrelated\nText.\n'}),embedder=Fake());self.assertEqual(g['links'][0]['method'],'embedding')
        for a,b in [([1.],[1.,2.]),([float('nan')],[1.])]:
            with self.assertRaises(DocMendError):cosine(a,b)

class RepairTests(unittest.TestCase):
    def setUp(self):self.e=analyze_files(BEFORE,AFTER)[0].edits[0]
    def test_stale_precondition(self):
        with self.assertRaises(DocMendError):patched_files({**AFTER,'docs/api.md':BEFORE['docs/api.md']+'modified\n'},[self.e])
    def test_overlapping_edits(self):
        with self.assertRaises(DocMendError):patched_files(AFTER,[self.e,self.e])
    def test_paths_and_structure(self):
        cases=[replace(self.e,path='../outside.md'),replace(self.e,path='.git/a.md'),replace(self.e,path='a.py'),replace(self.e,after=self.e.after.replace('# API','# Changed')),replace(self.e,after=self.e.after+'```\n'),replace(self.e,after=self.e.after+'[x](https://bad.invalid)\n')]
        for e in cases:
            with self.subTest(e=e):
                with self.assertRaises(DocMendError):validate_edit(e)
    def test_model_cannot_claim_safe(self):
        with self.assertRaises(DocMendError):validate_edit(replace(self.e,evidence='model'))
    def test_drafts_require_explicit_flag(self):
        e=replace(self.e,mode='draft',evidence='model');self.assertFalse(patched_files(AFTER,[e]));self.assertTrue(patched_files(AFTER,[e],include_drafts=True))
    def test_apply_and_stale_rerun(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'docs').mkdir();(root/'docs/api.md').write_text(AFTER['docs/api.md']);self.assertEqual(apply_local(root,[self.e]),['docs/api.md'])
            with self.assertRaises(DocMendError):apply_local(root,[self.e])
            self.assertFalse((root/'.docmend-apply.lock').exists())
    def test_symlinks_and_lock(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'docs').symlink_to(root,target_is_directory=True)
            with self.assertRaises(DocMendError):apply_local(root,[self.e])
            (root/'.docmend-apply.lock').write_text('active')
            with self.assertRaises(DocMendError):apply_local(root,[self.e])
    def test_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'docs').mkdir();(root/'docs/api.md').write_text(AFTER['docs/api.md']);(root/'second.md').write_text(AFTER['docs/api.md'])
            from docmend.repair import atomic_write
            def fail(path,text):
                if path.name=='second.md':raise OSError('injected disk failure')
                return atomic_write(path,text)
            with patch('docmend.repair.atomic_write',side_effect=fail):
                with self.assertRaises(OSError):apply_local(root,[self.e,replace(self.e,path='second.md')])
            self.assertEqual((root/'docs/api.md').read_text(),AFTER['docs/api.md'])

class ConfigTests(unittest.TestCase):
    def test_config_rejections(self):
        for t in ['unknown=3','max_files=0','max_sections=true','similarity_threshold=nan','include="x"','endpoint="http://bad.invalid"','endpoint="https://x:y@bad.invalid"']:
            with self.subTest(t=t):
                with self.assertRaises(DocMendError):Config.from_text(t)
    def test_default_globs(self):
        c=Config();self.assertTrue(c.accepts('pkg/api.py'));self.assertFalse(c.accepts('tests/test_x.py'));self.assertFalse(c.accepts('../out.py'))

class GitTests(unittest.TestCase):
    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            base,head=fixture(td)
            with patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(main(['check','--repo',td,'--base',base]),2)
            out=Path(td)/'.docmend/report';self.assertIn('timeout=60',(out/'safe.patch').read_text())
            with patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(main(['apply','--repo',td,'--report',str(out/'report.json')]),0)
            git(td,'add','docs/api.md');git(td,'commit','-m','repair')
            with patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(main(['check','--repo',td,'--base',head]),0)
    def test_forged_safe_report_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base,head=fixture(td);r,_,_=analyze_repository(GitStore(Path(td)),base,head);v=r.to_dict();v['edits'][0]['after']='# API\nForged.\n';p=Path(td)/'report.json';p.write_text(json.dumps(v))
            with patch('sys.stderr',new_callable=io.StringIO):self.assertEqual(main(['apply','--repo',td,'--report',str(p)]),3)
            self.assertEqual((Path(td)/'docs/api.md').read_text(),BEFORE['docs/api.md'])
    def test_dirty_worktree_not_executed(self):
        with tempfile.TemporaryDirectory() as td:
            base,head=fixture(td);(Path(td)/'api.py').write_text('raise SystemExit("untrusted")\n');self.assertEqual(len(analyze_repository(GitStore(Path(td)),base,head)[0].edits),1)
    def test_config_from_base_only(self):
        with tempfile.TemporaryDirectory() as td:
            base,_=fixture(td);(Path(td)/'.docmend.toml').write_text('endpoint="https://attacker.invalid"\nmodel="exfiltrate"\n');git(td,'add','.docmend.toml');git(td,'commit','-m','head config');self.assertEqual(GitStore(Path(td)).trusted_config(base).endpoint,'')
    def test_git_ref_and_size_limits(self):
        with tempfile.TemporaryDirectory() as td:
            base,_=fixture(td);s=GitStore(Path(td))
            for ref in ['--help','HEAD;touch /tmp/bad','$(echo bad)']:
                with self.assertRaises(DocMendError):s.resolve(ref)
            with self.assertRaises(DocMendError):s.snapshot(base,Config(max_file_bytes=5))
    def test_symlink_blobs_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            base,_=fixture(td);(Path(td)/'evil.md').symlink_to('/etc/passwd');git(td,'add','evil.md');git(td,'commit','-m','link');self.assertNotIn('evil.md',GitStore(Path(td)).snapshot(git(td,'rev-parse','HEAD'),Config()))
    def test_report_symlink_refused(self):
        with tempfile.TemporaryDirectory() as td:
            base,head=fixture(td);r,g,f=analyze_repository(GitStore(Path(td)),base,head);(Path(td)/'out').symlink_to(Path(td)/'docs',target_is_directory=True)
            with self.assertRaises(DocMendError):save(Path(td),'out',r,g,f)

class ModelTests(unittest.TestCase):
    def test_config_and_secret_required(self):
        with self.assertRaises(DocMendError):ModelProvider(Config())
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(DocMendError):ModelProvider(Config(endpoint='https://provider.invalid/v1',model='configured'))
    def model(self,answers):
        class Fake:
            def __init__(self):self.calls=0
            def json(self,*args):
                v=answers[self.calls];self.calls+=1;return v
        return Fake()
    def test_second_pass_stays_draft(self):
        f=self.model([{'status':'stale','reason':'body changed','confidence':.99},{'after':'# API\n\nCall `fetch(url, timeout=60)` and inspect the result.\n\n','reason':'draft'},{'accurate':True,'preserves_unaffected':True,'reason':'okay'}]);r,_=analyze_files(BEFORE,{**AFTER,'api.py':'def fetch(url, timeout=60):\n    return "new"\n'},provider=f);self.assertEqual(f.calls,3);self.assertEqual(r.edits[0].mode,'draft')
    def test_malformed_diagnosis(self):
        with self.assertRaises(DocMendError):analyze_files(BEFORE,{**BEFORE,'api.py':''},provider=self.model([{'status':'stale','reason':'x','confidence':'high'}]))
    def test_rejecting_critic(self):
        f=self.model([{'status':'stale','reason':'changed','confidence':1},{'after':'# API\nChanged.\n','reason':'draft'},{'accurate':False,'preserves_unaffected':False,'reason':'unsupported'}]);r,_=analyze_files(BEFORE,{**BEFORE,'api.py':''},provider=f);self.assertFalse(r.edits);self.assertEqual(r.findings[0].status,'review')
    def test_model_cannot_change_headings(self):
        f=self.model([{'status':'stale','reason':'changed','confidence':1},{'after':'# Malicious\nChanged.\n','reason':'draft'},{'accurate':True,'preserves_unaffected':True,'reason':'okay'}]);r,_=analyze_files(BEFORE,{**BEFORE,'api.py':''},provider=f);self.assertFalse(r.edits);self.assertIn('rejected',r.findings[0].reason)
