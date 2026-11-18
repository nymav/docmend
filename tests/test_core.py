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
        self.assertEqual(set(u),{'api.py::check','api.py::LIMIT','api.py::Settings','api.py::Settings.retries','api.py::Settings.run'})
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
        r,_=analyze_files(b,{**b,'api.py':AFTER['api.py']},cfg=Config(max_sections=1))
        self.assertTrue(r.incomplete);self.assertEqual(len(r.findings),1);self.assertIn('Incomplete analysis: 1 of 2',' '.join(r.warnings))
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


class ParsingAccuracyTests(unittest.TestCase):
    def test_setext_dash_heading_is_level_two(self):
        sections=parse_docs({'a.md':'Top\n===\nIntro\n\nSub\n---\nText\n'})
        self.assertIn('a.md#top-sub',sections)
    def test_fence_with_trailing_text_does_not_close(self):
        from docmend.diagnosis import _inline
        text='```\n``` not a close\n`hidden`\n```\nSignature: `shown`\n'
        self.assertEqual([v for _,_,v in _inline(text)],['shown'])
    def test_toml_keys_have_own_lines(self):
        units=parse_code({'a.toml':'name = "x"\n\n[http]\nretries = 2\ntimeout = 30\n'})
        self.assertEqual((units['a.toml::http.timeout'].line,units['a.toml::http.timeout'].end_line),(5,5))
        self.assertEqual(units['a.toml::name'].line,1)

class RepairReverificationTests(unittest.TestCase):
    def test_safe_repair_reverifies(self):
        from docmend.diagnosis import _verify_rewrite
        from docmend.changes import classify
        r,_=analyze_files(BEFORE,AFTER);self.assertEqual(r.edits[0].mode,'safe')
        change=classify(parse_code(BEFORE),parse_code(AFTER))[0]
        section=parse_docs(AFTER)['docs/api.md#api']
        self.assertTrue(_verify_rewrite(section,r.edits[0].after,change))
        self.assertFalse(_verify_rewrite(section,section.text,change))
    def test_unverifiable_rewrite_is_deferred(self):
        with patch('docmend.diagnosis._verify_rewrite',return_value=False):
            r,_=analyze_files(BEFORE,AFTER)
        self.assertFalse(r.edits);self.assertEqual(r.findings[0].status,'review');self.assertIn('re-verify',r.findings[0].reason)

class DraftBindingTests(unittest.TestCase):
    def draft_report(self,td,section_id,after):
        base,head=fixture(td);r,idx,_=analyze_repository(GitStore(Path(td)),base,head)
        s=next(x for x in idx['sections'] if x['id']==section_id)
        v=r.to_dict();v['edits']=[{'section_id':s['id'],'path':s['path'],'start':s['start'],'end':s['end'],'before':s['text'],'after':after,'file_hash':s['file_hash'],'mode':'draft','reason':'x','evidence':'model'}]
        p=Path(td)/'report.json';p.write_text(json.dumps(v));return p
    def test_draft_on_unflagged_section_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.draft_report(td,'docs/api.md#api-other','## Other\nInjected.\n')
            with patch('sys.stderr',new_callable=io.StringIO):self.assertEqual(main(['apply','--repo',td,'--report',str(p),'--include-drafts']),3)
            self.assertEqual((Path(td)/'docs/api.md').read_text(),BEFORE['docs/api.md'])
    def test_draft_on_flagged_section_applies(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.draft_report(td,'docs/api.md#api','# API\n\nSignature: `fetch(url, timeout=60)` (reviewed).\n\n')
            with patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(main(['apply','--repo',td,'--report',str(p),'--include-drafts']),0)
            self.assertIn('(reviewed)',(Path(td)/'docs/api.md').read_text())

class DraftMechanicalCheckTests(unittest.TestCase):
    def run_draft(self,after,doc=None):
        calls=[]
        answers=[{'status':'stale','reason':'changed','confidence':1},{'after':after,'reason':'draft'},{'accurate':True,'preserves_unaffected':True,'reason':'ok'}]
        class Fake:
            def json(self,*a):calls.append(1);return answers[len(calls)-1]
        before={**BEFORE,'docs/api.md':doc or BEFORE['docs/api.md']}
        r,_=analyze_files(before,{**before,'api.py':'def fetch(url, timeout=60):\n    return "new"\n'},provider=Fake())
        return r,len(calls)
    def test_invented_identifier_rejected(self):
        r,n=self.run_draft('# API\n\nSignature: `fetch(url, timeout=60, retries=3)`.\n\n')
        self.assertFalse(r.edits);self.assertIn('retries',r.findings[0].reason);self.assertEqual(n,2)
    def test_unrelated_inline_code_must_survive(self):
        doc='# API\n\nSignature: `fetch(url, timeout=30)`. Set `LOG_LEVEL`.\n\n## Other\nUntouched.\n'
        r,_=self.run_draft('# API\n\nSignature: `fetch(url, timeout=60)`.\n\n',doc)
        self.assertFalse(r.edits);self.assertIn('LOG_LEVEL',r.findings[0].reason)
    def test_supported_draft_passes(self):
        r,n=self.run_draft('# API\n\nSignature: `fetch(url, timeout=60)` returns `"new"`.\n\n')
        self.assertEqual(r.edits[0].mode,'draft');self.assertEqual(n,3)
    def test_reference_links_preserved(self):
        from docmend.models import Edit
        e=Edit('s','a.md',0,2,'# A\nSee [x].\n\n[x]: https://a.example\n','# A\nSee [x].\n\n','h','draft','r','model')
        with self.assertRaises(DocMendError):validate_edit(e)

class ProvenanceAuditTests(unittest.TestCase):
    def test_offline_provenance(self):
        r,_=analyze_files(BEFORE,AFTER);p=r.provenance
        self.assertEqual((p['mode'],p['model'],p['provider_host'],p['model_exchanges']),('offline',None,None,[]))
        self.assertEqual(len(p['config_sha256']),64);self.assertIn('provenance',json.loads(r.to_json()))
    def test_apply_writes_audit_line_without_text(self):
        with tempfile.TemporaryDirectory() as td:
            base,head=fixture(td);r,_,_=analyze_repository(GitStore(Path(td)),base,head)
            apply_local(Path(td),r.edits)
            lines=(Path(td)/'.docmend/audit.log').read_text().splitlines();self.assertEqual(len(lines),1)
            rec=json.loads(lines[0]);self.assertEqual(rec['action'],'apply');self.assertEqual(rec['files'][0]['path'],'docs/api.md')
            self.assertNotIn('timeout',lines[0])

class ShortNameLinkTests(unittest.TestCase):
    def test_common_name_in_prose_does_not_link(self):
        units=parse_code({'a.py':'def run(x=1):\n    return x\n'})
        self.assertFalse(build_index(units,parse_docs({'a.md':'# Setup\nRun the tests, then run again.\n'}))['links'])
    def test_common_name_in_code_links(self):
        units=parse_code({'a.py':'def run(x=1):\n    return x\n'})
        self.assertEqual(len(build_index(units,parse_docs({'a.md':'# Setup\nCall `run(x=1)`.\n'}))['links']),1)
    def test_qualified_name_links_in_prose(self):
        units=parse_code({'a.py':'class Job:\n    def run(self):\n        return 1\n'})
        links=build_index(units,parse_docs({'a.md':'# Jobs\nJob.run starts work.\n'}))['links']
        self.assertIn('a.py::Job.run',[l['unit'] for l in links])

class LocalRenameTests(unittest.TestCase):
    def semantic(self,src):return parse_code({'a.py':src})['a.py::f'].semantic
    def test_local_rename_is_not_behaviour(self):
        self.assertEqual(self.semantic('def f(x):\n    total = x + 1\n    return total\n'),self.semantic('def f(x):\n    result = x + 1\n    return result\n'))
    def test_real_changes_still_differ(self):
        base=self.semantic('def f(x):\n    total = x + 1\n    return total\n')
        self.assertNotEqual(base,self.semantic('def f(x):\n    total = x + 2\n    return total\n'))
        self.assertNotEqual(base,self.semantic('def f(x):\n    total = y + 1\n    return total\n'))
    def test_globals_are_not_renamed(self):
        self.assertNotEqual(self.semantic('def f():\n    global A\n    A = 1\n'),self.semantic('def f():\n    global B\n    B = 1\n'))

class RenameTests(unittest.TestCase):
    OLD={'api.py':'def fetch(url, timeout=30):\n    return url\n','docs/api.md':'# API\n\nSignature: `fetch(url, timeout=30)`.\n\n## Other\nUntouched.\n'}
    def test_rename_pairs_and_repairs_signature(self):
        new={**self.OLD,'api.py':'def download(url, timeout=30):\n    return url\n'}
        r,_=analyze_files(self.OLD,new)
        self.assertEqual([c['kind'] for c in r.changes],['renamed'])
        self.assertEqual(r.edits[0].mode,'safe');self.assertIn('`download(url, timeout=30)`',r.edits[0].after)
    def test_prose_mention_gets_rename_hint(self):
        old={**self.OLD,'docs/api.md':'# API\n\nUse fetch for downloads.\n'}
        r,_=analyze_files(old,{**old,'api.py':'def download(url, timeout=30):\n    return url\n'})
        self.assertFalse(r.edits);self.assertIn('renamed to download',r.findings[0].reason)
    def test_ambiguous_bodies_not_paired(self):
        old={'a.py':'def a():\n    pass\ndef b():\n    pass\n'}
        r,_=analyze_files(old,{'a.py':'def c():\n    pass\ndef d():\n    pass\n'})
        self.assertNotIn('renamed',[c['kind'] for c in r.changes])

class BaselineTests(unittest.TestCase):
    REVIEW={**AFTER,'api.py':'def fetch(url, timeout=60):\n    return "changed"\n'}
    def test_baseline_acknowledges_exact_review_only(self):
        from docmend.pipeline import load_baseline
        r,_=analyze_files(BEFORE,self.REVIEW);f=r.findings[0];self.assertEqual(f.status,'review')
        pairs=load_baseline(json.dumps({'version':1,'acknowledged':[{'section_id':f.section_id,'fingerprint':f.fingerprint}]}))
        r2,_=analyze_files(BEFORE,self.REVIEW,baseline=pairs);self.assertTrue(r2.findings[0].acknowledged)
        changed={**self.REVIEW,'api.py':'def fetch(url, timeout=60):\n    return "again"\n'}
        r3,_=analyze_files(BEFORE,changed,baseline=pairs);self.assertFalse(r3.findings[0].acknowledged)
    def test_stale_is_never_acknowledged(self):
        r,_=analyze_files(BEFORE,AFTER);f=r.findings[0];self.assertEqual(f.status,'stale')
        r2,_=analyze_files(BEFORE,AFTER,baseline={(f.section_id,f.fingerprint)});self.assertFalse(r2.findings[0].acknowledged)
    def test_invalid_baseline_rejected(self):
        from docmend.pipeline import load_baseline
        with self.assertRaises(DocMendError):load_baseline('{"version":2}')
    def test_cli_baseline_then_check_passes(self):
        with tempfile.TemporaryDirectory() as td:
            fixture(td);root=Path(td)
            (root/'api.py').write_text(self.REVIEW['api.py']);git(td,'commit','-am','behaviour');head=git(td,'rev-parse','HEAD');base=git(td,'rev-parse','HEAD~1')
            with patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(main(['check','--repo',td,'--base',base,'--head',head]),2)
            with patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(main(['baseline','--repo',td,'--base',base,'--head',head]),0)
            # The baseline only counts once it is in the base commit.
            with patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(main(['check','--repo',td,'--base',base,'--head',head]),2)
            git(td,'checkout','-q',base);git(td,'add','.docmend-baseline.json');git(td,'commit','-qm','baseline');newbase=git(td,'rev-parse','HEAD')
            git(td,'checkout','-q',head);git(td,'merge','-q','--no-edit',newbase);newhead=git(td,'rev-parse','HEAD')
            with patch('sys.stdout',new_callable=io.StringIO) as out:code=main(['check','--repo',td,'--base',newbase,'--head',newhead])
            self.assertEqual(code,0,out.getvalue())
    def test_baseline_file_is_not_source(self):
        self.assertEqual(parse_code({'.docmend-baseline.json':'{"version":1,"acknowledged":[]}'}),{})

class TokenIndexLinkTests(unittest.TestCase):
    def test_token_index_matches_regex(self):
        import re as _re
        from docmend.mapping import explicit, weak_name, _code_spans
        units=parse_code({'a.py':'def fetch_all(x):\n    return x\nclass Job:\n    def run(self):\n        return 1\nLIMIT = 3\n'})
        docs=parse_docs({'a.md':'# A\nfetch_all and Job.run, LIMITS not LIMIT_X; LIMIT.\n## B\nprefetch_all only, `run` here.\n'})
        hit=lambda n,t:_re.search(r'(?<![\w])'+_re.escape(n)+r'(?![\w])',t) is not None
        for s in docs.values():
            for u in units.values():
                short=u.name.rsplit('.',1)[-1]
                prose=([u.name] if u.name!=short else [])+([] if weak_name(short) else [short])
                slow=any(hit(n,s.text) for n in prose) or (weak_name(short) and hit(short,_code_spans(s.text)))
                self.assertEqual(explicit(s,u,{}),slow,(s.id,u.id))

class ConfidenceGateTests(unittest.TestCase):
    NEW={**AFTER,'api.py':'def fetch(url, timeout=60):\n    return "new"\n'}
    DRAFT=[{'after':'# API\n\nSignature: `fetch(url, timeout=60)`.\n\n','reason':'d'},{'accurate':True,'preserves_unaffected':True,'reason':'ok'}]
    def fake(self,answers):
        class F:
            calls=0
            def json(s,*a):
                v=answers[F.calls];F.calls+=1;return v
        return F()
    def test_low_confidence_stale_becomes_review(self):
        f=self.fake([{'status':'stale','reason':'r','confidence':.4}])
        r,_=analyze_files(BEFORE,self.NEW,provider=f,cfg=Config(min_stale_confidence=.7))
        self.assertEqual(r.findings[0].status,'review');self.assertFalse(r.edits);self.assertIn('below',r.findings[0].reason)
    def test_disagreement_becomes_review(self):
        f=self.fake([{'status':'stale','reason':'r','confidence':.9},{'status':'accurate','reason':'r','confidence':.9}])
        r,_=analyze_files(BEFORE,self.NEW,provider=f,cfg=Config(require_agreement=True))
        self.assertEqual(r.findings[0].status,'review');self.assertIn('disagreed',r.findings[0].reason)
    def test_agreement_keeps_stale(self):
        f=self.fake([{'status':'stale','reason':'r','confidence':.9},{'status':'stale','reason':'r','confidence':.8},*self.DRAFT])
        r,_=analyze_files(BEFORE,self.NEW,provider=f,cfg=Config(require_agreement=True))
        self.assertEqual(r.findings[0].status,'stale');self.assertEqual(r.findings[0].confidence,.8);self.assertEqual(r.edits[0].mode,'draft')
    def test_config_validation(self):
        with self.assertRaises(DocMendError):Config.from_text('min_stale_confidence = 2.0')
        with self.assertRaises(DocMendError):Config.from_text('require_agreement = 1')
        self.assertTrue(Config.from_text('require_agreement = true').require_agreement)

class PartialResultTests(unittest.TestCase):
    def test_contract_changes_checked_first(self):
        b={'api.py':'def fetch(url, timeout=30):\n    return url\ndef other(x):\n    return x\n','docs/a.md':'# A\nother does things.\n','docs/z.md':'# Z\nSignature: `fetch(url, timeout=30)`.\n'}
        a={**b,'api.py':'def fetch(url, timeout=60):\n    return url\ndef other(x):\n    return x + 1\n'}
        r,_=analyze_files(b,a,cfg=Config(max_sections=1))
        self.assertEqual([f.section_id for f in r.findings],['docs/z.md#z']);self.assertTrue(r.incomplete)
    def test_incomplete_fails_check_unless_never(self):
        from docmend.reporting import summary,markdown
        r,_=analyze_files({**BEFORE,'x.md':'# X\n`fetch(url, timeout=30)`\n'},{**AFTER,'x.md':'# X\n`fetch(url, timeout=30)`\n'},cfg=Config(max_sections=1))
        self.assertEqual(summary(r)['incomplete'],1);self.assertIn('Incomplete analysis',markdown(r))

class StagedCheckTests(unittest.TestCase):
    def test_staged_change_detected(self):
        with tempfile.TemporaryDirectory() as td:
            fixture(td);root=Path(td)
            (root/'api.py').write_text('def fetch(url, timeout=90):\n    return url\n');git(td,'add','api.py')
            with patch('sys.stdout',new_callable=io.StringIO) as out:code=main(['check','--repo',td,'--staged'])
            self.assertEqual(code,2);self.assertEqual(json.loads(out.getvalue())['changed_units'],1)
    def test_unstaged_edits_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            fixture(td);(Path(td)/'api.py').write_text('def fetch(url, timeout=90):\n    return url\n')
            with patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(main(['check','--repo',td,'--staged','--fail-on','stale']),0)
    def test_base_still_required_without_staged(self):
        with tempfile.TemporaryDirectory() as td:
            fixture(td)
            with patch('sys.stderr',new_callable=io.StringIO):self.assertEqual(main(['check','--repo',td]),3)

class FlagAndFieldRepairTests(unittest.TestCase):
    def test_argparse_flag_default_repaired_in_both_styles(self):
        cli='import argparse\np=argparse.ArgumentParser()\np.add_argument("--port", type=int, default={})\np.add_argument("--mode", default="{}")\n'
        doc='# CLI\n\nDefault: `--port 8000`.\nDefault: `--mode=fast`.\n'
        b={'cli.py':cli.format(8000,'fast'),'docs/cli.md':doc}
        r,_=analyze_files(b,{**b,'cli.py':cli.format(9000,'fast')})
        self.assertIn('`--port 9000`',r.edits[0].after);self.assertEqual(r.edits[0].mode,'safe')
        r,_=analyze_files(b,{**b,'cli.py':cli.format(8000,'slow')})
        self.assertIn('`--mode=slow`',r.edits[0].after)
    def test_dataclass_field_default_repaired(self):
        code='from dataclasses import dataclass\n@dataclass\nclass Settings:\n    retries: int = {}\n'
        doc='# Settings\n\nThe Settings class.\n\nDefault: `retries=3`.\n'
        b={'s.py':code.format(3),'docs/s.md':doc}
        r,_=analyze_files(b,{**b,'s.py':code.format(5)})
        self.assertEqual([c['kind'] for c in r.changes],['contract']);self.assertIn('`retries=5`',r.edits[0].after)
    def test_field_short_name_needs_class_in_section(self):
        code='class Settings:\n    retries: int = {}\n'
        b={'s.py':code.format(3),'docs/s.md':'# Other\n\nDefault: `retries=3`.\n'}
        r,_=analyze_files(b,{**b,'s.py':code.format(5)})
        self.assertFalse(r.edits)

class EmbeddingCacheTests(unittest.TestCase):
    def test_each_distinct_text_embedded_once(self):
        sent=[]
        class Fake:
            def embed(self,texts):sent.extend(texts);return [[1.,float(len(t))] for t in texts]
        _,idx=analyze_files(BEFORE,AFTER,semantic=True,embedder=Fake())
        self.assertEqual(len(sent),len(set(sent)))
        units_and_docs=4+3  # fetch before/after differ; docs identical across snapshots
        self.assertLess(len(sent),2*units_and_docs);self.assertEqual(idx['operations']['embedded_texts'],len(sent))
    def test_results_match_uncached(self):
        from docmend.mapping import CachingEmbedder
        class Fake:
            def embed(self,texts):return [[1.,float(len(t))] for t in texts]
        texts=['a','bb','a','ccc','bb']
        self.assertEqual(CachingEmbedder(Fake()).embed(texts),Fake().embed(texts))

class DocstringTests(unittest.TestCase):
    SRC='def fetch(url, timeout={}):\n    """Fetch a URL.\n\n    Default: `fetch(url, timeout=30)`.\n    """\n    return {}\n'
    def test_off_by_default(self):
        b={'api.py':self.SRC.format(30,'url')}
        r,_=analyze_files(b,{'api.py':self.SRC.format(60,'url')})
        self.assertFalse(r.findings)
    def test_signature_change_flags_docstring_without_edit(self):
        b={'api.py':self.SRC.format(30,'url')}
        r,_=analyze_files(b,{'api.py':self.SRC.format(60,'url')},cfg=Config(docstrings=True))
        self.assertEqual([f.section_id for f in r.findings],['api.py::fetch#docstring']);self.assertFalse(r.edits)
        self.assertIn('by hand',r.findings[0].reason)
    def test_body_change_does_not_flag_docstring(self):
        b={'api.py':self.SRC.format(30,'url')}
        r,_=analyze_files(b,{'api.py':self.SRC.format(30,'url + "/"')},cfg=Config(docstrings=True))
        self.assertFalse(r.findings)

class ScopeTests(unittest.TestCase):
    FILES={'pkg/a/api.py':'def fetch(url, timeout=30):\n    return url\n','pkg/b/api.py':'def fetch(url, timeout=30):\n    return url\n',
           'pkg/a/README.md':'# A\nSignature: `fetch(url, timeout=30)`.\n','pkg/b/README.md':'# B\nSignature: `fetch(url, timeout=30)`.\n','README.md':'# Root\nSignature: `fetch(url, timeout=30)`.\n'}
    def test_scoped_docs_link_only_own_package(self):
        after={**self.FILES,'pkg/a/api.py':'def fetch(url, timeout=60):\n    return url\n'}
        r,_=analyze_files(self.FILES,after,cfg=Config(scopes=('pkg/a','pkg/b')))
        self.assertEqual(sorted(f.section_id for f in r.findings),['README.md#root','pkg/a/README.md#a'])
    def test_without_scopes_everything_links(self):
        after={**self.FILES,'pkg/a/api.py':'def fetch(url, timeout=60):\n    return url\n'}
        r,_=analyze_files(self.FILES,after)
        self.assertEqual(len(r.findings),3)
    def test_invalid_scope_rejected(self):
        for bad in ['scopes = ["../x"]','scopes = ["pkg/*"]','scopes = "pkg"']:
            with self.assertRaises(DocMendError):Config.from_text(bad)


class HistoryDocTests(unittest.TestCase):
    def test_history_docs_are_skipped_by_default(self):
        from docmend.config import is_history_doc
        for p in ['CHANGELOG.md', 'CHANGES.rst', 'HISTORY.md', 'NEWS', 'docs/release-notes.md', 'docs/changelog/v2.md', 'whatsnew.rst']:
            self.assertTrue(is_history_doc(p), p)
            self.assertFalse(Config().accepts(p), p)
        for p in ['README.md', 'docs/release-process.rst', 'docs/history_of_api.md', 'changes.py', 'docs/api.md']:
            self.assertFalse(is_history_doc(p), p)
        self.assertTrue(Config.from_text('skip_history_docs = false\n').accepts('CHANGELOG.md'))
    def test_changelog_never_flagged(self):
        b={**BEFORE,'CHANGELOG.md':'# 1.0\n\nSignature: `fetch(url, timeout=30)`.\n'}
        r,_=analyze_files(b,{**b,'api.py':AFTER['api.py']})
        self.assertEqual([f.path for f in r.findings],['docs/api.md'])


class BehaviourScopeTests(unittest.TestCase):
    CODE_B={'m.py':'def echo(x):\n    return x\n'}
    CODE_A={'m.py':'def echo(x):\n    return str(x)\n'}
    def run_doc(self, doc, scope):
        b={**self.CODE_B,'docs/a.md':doc}
        return analyze_files(b,{**b,**self.CODE_A},cfg=Config(behaviour_scope=scope))[0]
    def test_default_flags_every_mention(self):
        self.assertEqual(len(self.run_doc('# Usage\n\nCall `echo` here.\n','all').findings),1)
    def test_subject_skips_passing_mentions_and_counts_them(self):
        r=self.run_doc('# Usage\n\nCall `echo` here.\n','subject')
        self.assertEqual((r.findings,r.behaviour_mentions_skipped),([],1))
    def test_subject_keeps_sections_about_the_unit(self):
        for doc in ['# echo\n\nPrints.\n','# Usage\n\n`echo` prints; `echo` returns.\n']:
            self.assertEqual(len(self.run_doc(doc,'subject').findings),1,doc)
    def test_invalid_scope(self):
        with self.assertRaises(DocMendError):Config.from_text('behaviour_scope = "some"\n')
