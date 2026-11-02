"""Reproducible local demo and explicitly synthetic evaluation; no cloud calls."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from docmend.config import Config
from docmend.gitstore import GitStore
from docmend.models import digest
from docmend.pipeline import analyze_files, analyze_repository
from docmend.repair import apply_local
from docmend.reporting import save, summary


def git(root,*args):
    return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL).decode().strip()


def evaluate():
    base_code='def fetch(url, timeout=30):\n    return url\n'
    changed='def fetch(url, timeout=60):\n    return url\n'
    docs='# API\nSignature: `fetch(url, timeout=30)`.\n'
    cases=[
        ('default-change',base_code,changed,docs,docs,'stale',True),
        ('parameter-rename',base_code,base_code.replace('timeout','wait'),docs,docs,'stale',True),
        ('removed-api',base_code,'',docs,docs,'review',False),
        ('body-change',base_code,base_code.replace('return url','return "new"'),docs,docs,'review',False),
        ('body-and-default',base_code,changed.replace('return url','return "new"'),docs,docs,'review',False),
        ('comment-only',base_code,'# Changed comment\n'+base_code,docs,docs,'none',False),
        ('whitespace-only',base_code,base_code.replace('timeout=30','timeout = 30'),docs,docs,'none',False),
        ('docstring-only',base_code,base_code.replace('    return','    """A description."""\n    return'),docs,docs,'none',False),
        ('docs-already-current',base_code,changed,docs,docs.replace('30','60'),'accurate',False),
        ('documentation-only',base_code,base_code,docs,docs+'More context.\n','none',False),
        ('no-changes',base_code,base_code,docs,docs,'none',False),
        ('unsupported-prose',base_code,changed,'# API\nfetch has a timeout.\n','# API\nfetch has a timeout.\n','review',False),
    ]
    outcomes=[]
    for name,b,a,bd,ad,expected,repair in cases:
        report,_=analyze_files({'api.py':b,'docs/api.md':bd},{'api.py':a,'docs/api.md':ad})
        actual=report.findings[0].status if report.findings else 'none'
        outcomes.append({'case':name,'expected_status':expected,'status':actual,'expected_safe_repair':repair,'safe_repairs':sum(e.mode=='safe' for e in report.edits),'passed':actual==expected and bool(report.edits)==repair})
    assert all(c['passed'] for c in outcomes)
    return {'dataset':'12 constructed development fixtures; not a human-reviewed held-out benchmark','outcomes':outcomes,'passed':sum(c['passed'] for c in outcomes),'total':len(outcomes),'interpretation':'Review is abstention/manual triage, not a confirmed stale diagnosis. No broad detection accuracy claim is made.'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=Path('artifacts/demo'));ap.add_argument('--real-repo',type=Path);args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='docmend-demo-') as td:
        root=Path(td);git(root,'init','-b','main');git(root,'config','user.name','DocMend Demo');git(root,'config','user.email','demo@example.invalid')
        if args.real_repo:
            source=GitStore(args.real_repo);files=source.snapshot(source.resolve('HEAD'),Config())
            for name,text in files.items():
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
            # Pick an actual top-level function with a literal numeric default.
            from docmend.codeparse import parse_code
            import ast
            chosen=None
            for unit in parse_code(files).values():
                if unit.kind=='function' and '.' not in unit.name:
                    for key,value in unit.facts['params'].items():
                        try:num=ast.literal_eval(value) if value is not None else None
                        except (ValueError,SyntaxError):continue
                        if type(num) is int and 0<num<1000:
                            chosen=(unit,key,num);break
                if chosen:break
            if not chosen:raise RuntimeError('No suitable real numeric-default function found')
            unit,key,num=chosen
            code_path=unit.path;old_code=files[code_path]
            # Replace exactly the default's AST source location, not arbitrary text.
            tree=ast.parse(old_code);node=next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==unit.name)
            positional=node.args.posonlyargs+node.args.args
            default_nodes={a.arg:v for a,v in zip(positional[len(positional)-len(node.args.defaults):],node.args.defaults)}
            default_nodes.update({a.arg:v for a,v in zip(node.args.kwonlyargs,node.args.kw_defaults)})
            default=default_nodes[key];lines=old_code.splitlines(keepends=True)
            # AST columns are UTF-8 offsets; modify the original encoded line.
            raw=lines[default.lineno-1].encode();lines[default.lineno-1]=(raw[:default.col_offset]+str(num+1).encode()+raw[default.end_col_offset:]).decode()
            new_code=''.join(lines);doc_text='# DocMend controlled integration fixture\n\nSignature: `'+unit.facts['signature']+'`\n'
            provenance={'source_repository':str(args.real_repo),'source_commit':source.resolve('HEAD'),'actual_unit':unit.id,'changed_default':key,'default_before':num,'default_after':num+1,'synthetic_documentation':True,'note':'Uses a real repository snapshot and one deliberately added documentation fixture; not a live GitHub fork or production evaluation.'}
        else:
            code_path='api.py';old_code='def fetch(url, timeout=30):\n    return url\n';new_code=old_code.replace('timeout=30','timeout=60');doc_text='# API\n\nSignature: `fetch(url, timeout=30)`.\n';provenance={'source':'constructed end-to-end demo'}
        target=root/code_path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(old_code)
        docpath='docs/docmend-integration-fixture.md';(root/'docs').mkdir(exist_ok=True);(root/docpath).write_text(doc_text)
        git(root,'add','.');git(root,'commit','-m','baseline with explicit documentation');base=git(root,'rev-parse','HEAD')
        target.write_text(new_code);git(root,'add',code_path);git(root,'commit','-m','change documented default');head=git(root,'rev-parse','HEAD')
        report,index,files=analyze_repository(GitStore(root),base,head)
        save(root,'docmend-report',report,index,files)
        assert report.edits,'Expected deterministic repair'
        shutil.copytree(root/'docmend-report',out/'before-repair',dirs_exist_ok=True)
        applied=apply_local(root,report.edits);git(root,'add',*applied);git(root,'commit','-m','repair documentation')
        repaired=git(root,'rev-parse','HEAD');post,postindex,postfiles=analyze_repository(GitStore(root),base,repaired);save(root,'post-report',post,postindex,postfiles);shutil.copytree(root/'post-report',out/'after-repair',dirs_exist_ok=True)
        assert not any(f.status=='stale' for f in post.findings)
        provenance.update({'base':base,'head':head,'repaired':repaired,'before':summary(report),'after':summary(post),'applied':applied})
        (out/'run.json').write_text(json.dumps(provenance,indent=2)+'\n');(out/'fixture-evaluation.json').write_text(json.dumps(evaluate(),indent=2)+'\n')
        (out/'DEMO.txt').write_text('1. Create baseline commit with a documented default.\n2. Change that default in code, leaving docs stale.\n3. Run check: inspect before-repair/summary.md and safe.patch.\n4. Apply guarded edit; commit only repaired Markdown.\n5. Recheck: after-repair/ compares the original base to repaired head; any remaining review findings are retained.\n\n'+json.dumps(provenance,indent=2))
        print(json.dumps(provenance,indent=2))
if __name__=='__main__':main()
