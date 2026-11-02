"""Author explicit development/challenge fixtures. Refuses to overwrite a frozen set."""
from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parents[1]/'evals'

def case(key,family,before,after,docs,stale,*,updated=None,gold=None,split='development',rationale=''):
    # Labels describe each complete non-overlapping section, not the tool's output.
    if isinstance(before,str):before={'pkg/api.py':before}
    if isinstance(after,str):after={'pkg/api.py':after}
    current=updated or docs
    return {'id':key,'split':split,'family':family,'before':{**before,'README.md':docs},'after':{**after,'README.md':current},'labels':[{'path':'README.md','heading':'API','stale':stale,'rationale':rationale}],'gold_files':{'README.md':gold if gold is not None else current},'provenance':{'kind':'constructed','label_author':'AI-assisted authoring; not independently human-reviewed','natural_repository_history':False}}

def fn(args='timeout=30',body='return 1',name='fetch',prefix='def'):
    return f'{prefix} {name}({args}):\n    {body}\n'
def doc(s):return '# API\n\n'+s+'\n'
D=[]
def add(k,f,b,a,d,y,**kwargs):D.append(case('dev-'+k,f,b,a,d,y,**kwargs))
# Directly verifiable positive examples.
for key,args,newargs in [('int','timeout=30','timeout=60'),('string',"mode='safe'","mode='strict'"),('boolean','enabled=True','enabled=False'),('keyword-only','*, retries=2','*, retries=4'),('positional-only','x=1, /','x=2, /'),('required-add','x','x, y'),('parameter-remove','x, y=2','x'),('annotated','timeout: int = 30','timeout: int = 60')]:
    old=fn(args);new=fn(newargs);text=doc('Signature: `'+old.splitlines()[0][4:-1]+'`.');gold=doc('Signature: `'+new.splitlines()[0][4:-1]+'`.')
    add(key,'signature-contract',old,new,text,True,gold=gold,rationale='The declared signature differs from the new function contract.')
add('config','config-default','LIMIT=10\n','LIMIT=20\n',doc('Default: `LIMIT=10`.'),True,gold=doc('Default: `LIMIT=20`.'),rationale='Explicit declared configuration value changed.')
add('toml','config-default',{'app.toml':'[http]\ntimeout=30\n'},{'app.toml':'[http]\ntimeout=60\n'},doc('Default: `http.timeout=30`.'),True,gold=doc('Default: `http.timeout=60`.'),rationale='The declared TOML-key default changed.')
add('removed','removed-feature',fn(),'',doc('The fetch function is available.'),True,gold=doc('The fetch function was removed.'),rationale='Documentation advertises an API removed from source.')
add('behaviour','behaviour',fn(body='return 1'),fn(body='return 2'),doc('fetch returns 1.'),True,gold=doc('fetch returns 2.'),rationale='The stated return value contradicts the changed function body.')
add('mixed','combined-change',fn(),fn('timeout=60',body='return 2'),doc('Signature: `fetch(timeout=30)`. fetch returns 1.'),True,gold=doc('Signature: `fetch(timeout=60)`. fetch returns 2.'),rationale='Both a declared signature and behaviour description changed.')
add('schema','class-schema','class Settings:\n    retries: int = 2\n','class Settings:\n    retries: int = 5\n',doc('Settings uses retries=2.'),True,gold=doc('Settings uses retries=5.'),rationale='A named class field default contradicts the documentation.')
# Negatives that should resist automatic repair.
b=fn();a=fn('timeout=60');declaration=doc('Signature: `fetch(timeout=30)`.')
add('comment','nonsemantic',b,'# only a comment\n'+b,declaration,False,rationale='Comments do not change the declared function contract.')
add('format','nonsemantic',b,b.replace('timeout=30','timeout = 30'),declaration,False,rationale='Formatting only; same AST.')
add('docstring','nonsemantic',b,b.replace('    return','    """New description."""\n    return'),declaration,False,rationale='Only a source docstring changed.')
add('already-updated','coordinated-doc-update',b,a,declaration,False,updated=declaration.replace('30','60'),rationale='Documentation was updated in the same change.')
add('intentional-override','intentional-override',b,a,doc('Call `fetch(timeout=30)` to override the new default.'),False,rationale='An explicit valid override remains valid after a default change.')
add('generic-prose','unaffected-prose',b,a,doc('fetch returns 1.'),False,rationale='Only a default changed; the documented return remains correct.')
add('unrelated-section','unrelated-doc',b,a,doc('Installation requires Python.'),False,rationale='The section makes no claim about the changed default.')
add('doc-only','docs-only',b,b,doc('Use fetch.'),False,updated=doc('Use the fetch helper.'),rationale='No source code changed.')
add('unchanged','unchanged',b,b,declaration,False,rationale='No input changed.')
add('override-same-section','mixed-validity',b,a,doc('Signature: `fetch(timeout=30)`.\n\nOverride example: `fetch(timeout=10)`.'),True,gold=doc('Signature: `fetch(timeout=60)`.\n\nOverride example: `fetch(timeout=10)`.'),rationale='Only the declared default changes; the example must be preserved.')
add('historical-label','historical-documentation',b,a,doc('Previous signature: `fetch(timeout=30)`.'),False,rationale='A historical signature remains a correct description of the past.')
add('historical-prose','historical-documentation',b,a,doc('Old signature: `fetch(timeout=30)`.'),False,rationale='Explicitly old contract must not be silently rewritten as historical fact.')
add('hidden-comment','hidden-html',b,a,doc('<!--\nSignature: `fetch(timeout=30)`.\n-->\nPublic docs do not state a default.'),False,rationale='Hidden HTML-comment content is not an active public contract declaration.')
add('multiple-claims','mixed-validity',b,a,doc('Signature: `fetch(timeout=30)`.\n\nDefault: `fetch(timeout=30)`.'),True,gold=doc('Signature: `fetch(timeout=60)`.\n\nDefault: `fetch(timeout=60)`.'),rationale='Both explicit declarations must change together.')
# Challenge inputs are committed before development fixes; they are not a blind,
# independently authored benchmark. Do not tune on this split and call it held out.
C=[]
def challenge(k,f,b,a,d,y,**kwargs):C.append(case('challenge-'+k,f,b,a,d,y,split='challenge',**kwargs))
for key,args,newargs,prefix in [('float','delay=0.25','delay=0.5','def'),('none','limit=None','limit=100','def'),('escaped-string',"sep='\\t'","sep=','",'def'),('async','timeout=10','timeout=20','async def'),('varargs','*items, strict=False','*items, strict=True','def'),('negative','offset=-1','offset=-2','def')]:
    old=fn(args,name='load',prefix=prefix);new=fn(newargs,name='load',prefix=prefix)
    osig=old.splitlines()[0].removeprefix(prefix+' ')[:-1];nsig=new.splitlines()[0].removeprefix(prefix+' ')[:-1]
    challenge(key,'signature-variation',old,new,doc('Signature: `'+osig+'`.'),True,gold=doc('Signature: `'+nsig+'`.'),rationale='The declaration is contradicted by a changed literal/argument contract.')
challenge('toml-bool','config-variation',{'svc.toml':'enabled=true\n'},{'svc.toml':'enabled=false\n'},doc('Default: `enabled=true`.'),True,gold=doc('Default: `enabled=false`.'),rationale='Explicit boolean config default changed.')
challenge('toml-string','config-variation',{'svc.toml':'mode="safe"\n'},{'svc.toml':'mode="strict"\n'},doc('Default: `mode="safe"`.'),True,gold=doc('Default: `mode="strict"`.'),rationale='Explicit string config default changed.')
challenge('route','route-change','@app.get("/old")\ndef health():\n    return 1\n','@app.get("/new")\ndef health():\n    return 1\n',doc('The health endpoint is `/old`.'),True,gold=doc('The health endpoint is `/new`.'),rationale='The documented route no longer matches the decorator.')
challenge('cli','cli-change','@app.command("start")\ndef main():\n    return 1\n','@app.command("serve")\ndef main():\n    return 1\n',doc('Use the start command.'),True,gold=doc('Use the serve command.'),rationale='A named command in the decorator changed.')
challenge('fenced-declaration','fenced-declaration',fn(),fn('timeout=60'),doc('fetch signature:\n```python\nfetch(timeout=30)\n```'),True,gold=doc('fetch signature:\n```python\nfetch(timeout=60)\n```'),rationale='The fenced signature is stale even if the conservative inline rule abstains.')
challenge('multiline-declaration','multiline-declaration',fn(),fn('timeout=60'),doc('Signature for fetch:\n`fetch(\n timeout=30\n)`'),True,gold=doc('Signature for fetch:\n`fetch(\n timeout=60\n)`'),rationale='A multiline declared default changed.')
challenge('two-symbols','multiple-unit-change',fn(name='alpha')+fn('n=1',name='beta'),fn('timeout=60',name='alpha')+fn('n=2',name='beta'),doc('Signature: `alpha(timeout=30)`.\nSignature: `beta(n=1)`.'),True,gold=doc('Signature: `alpha(timeout=60)`.\nSignature: `beta(n=2)`.'),rationale='Two independent declared contracts need coordinated edits.')
challenge('qualified-collision','ambiguous-symbol','class A:\n    def run(self, n=1):\n        return n\nclass B:\n    def run(self, n=1):\n        return n\n','class A:\n    def run(self, n=2):\n        return n\nclass B:\n    def run(self, n=1):\n        return n\n',doc('A.run signature: `run(self, n=1)`.'),True,gold=doc('A.run signature: `run(self, n=2)`.'),rationale='Only the qualified A.run declaration is stale; name collision requires disambiguation.')
challenge('deprecated-history','historical-documentation',fn(),fn('timeout=60'),doc('Deprecated signature: `fetch(timeout=30)`.'),False,rationale='The recorded deprecated signature remains historically accurate.')
challenge('old-example','intentional-override',fn(),fn('timeout=60'),doc('Example override: `fetch(timeout=30)`.'),False,rationale='The explicitly selected timeout remains permitted.')
challenge('comment-block','nonsemantic',fn(),'# explanation\n\n'+fn(),doc('Signature: `fetch(timeout=30)`.'),False,rationale='Only comments and blank lines changed.')
challenge('already-updated-async','coordinated-doc-update',fn('n=1',name='load',prefix='async def'),fn('n=2',name='load',prefix='async def'),doc('Signature: `load(n=1)`.'),False,updated=doc('Signature: `load(n=2)`.'),rationale='The async function declaration is current in the after snapshot.')
challenge('return-still-valid','unaffected-prose',fn(),fn('timeout=45'),doc('The fetch helper returns 1.'),False,rationale='Default changed but the stated behaviour did not.')
challenge('removed-mentioned-as-removed','coordinated-doc-update',fn(),'',doc('fetch is available.'),False,updated=doc('fetch has been removed.'),rationale='The documentation accurately records a deletion.')
challenge('unrelated-module','unrelated-doc',{'pkg/api.py':fn(),'pkg/other.py':'def other(x=1): return x\n'},{'pkg/api.py':fn(),'pkg/other.py':'def other(x=2): return x\n'},doc('Signature: `fetch(timeout=30)`.'),False,rationale='A different unreferenced function changed.')
challenge('tests-only','excluded-tests',{'pkg/api.py':fn(),'tests/test_api.py':'def test_x(): return 1\n'},{'pkg/api.py':fn(),'tests/test_api.py':'def test_x(): return 2\n'},doc('Signature: `fetch(timeout=30)`.'),False,rationale='Only an excluded test file changed.')
challenge('annotation-format','nonsemantic',fn('n: int = 1'),fn('n:int=1'),doc('Signature: `fetch(n: int=1)`.'),False,rationale='Only spaces in an annotation changed; same AST.')
challenge('hidden-previous','hidden-html',fn(),fn('timeout=60'),doc('<!-- Previous signature: `fetch(timeout=30)`. -->\nfetch still returns 1.'),False,rationale='Hidden historical text is not an active declaration.')

if __name__=='__main__':
    ROOT.mkdir(exist_ok=True)
    for split,items in [('development',D),('challenge',C)]:
        path=ROOT/(split+'.jsonl')
        if path.exists():raise SystemExit(f'Refusing to overwrite frozen {path}')
        path.write_text(''.join(json.dumps(c,ensure_ascii=False,sort_keys=True)+'\n' for c in items))
    manifest={'schema_version':1,'created':'2026-11-03','label_provenance':'AI-authored constructed labels; not independently human reviewed','splits':{s:{'count':len(c),'sha256':hashlib.sha256((ROOT/(s+'.jsonl')).read_bytes()).hexdigest()} for s,c in [('development',D),('challenge',C)]},'policy':'Develop against development only. Challenge is reserved from tuning; same author and related task grammar mean it is not an independent real-world test set.'}
    (ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2))
