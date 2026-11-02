"""Freeze mutations of real local Git snapshots; never modify those repositories."""
from pathlib import Path
import ast,hashlib,json
from docmend.codeparse import parse_python
from docmend.config import Config
from docmend.gitstore import GitStore
from docmend.models import DocMendError

ROOT=Path(__file__).resolve().parents[1]
SOURCES={
'docatlas':Path('/Users/yarra/Documents/Codex/2026-10-06/fix/work/docatlas-community'),
'mailayer':Path('/Users/yarra/Documents/Codex/2026-10-19/so-x20/work/mailayer'),
'drax-tbs':Path('/Users/yarra/Documents/Codex/2026-10-19/so-x20/work/drax_tbs'),
}

def main():
    output=ROOT/'evals/source-backed.jsonl'
    if output.exists():raise SystemExit('Refusing to overwrite frozen source-backed cases')
    cases=[];source_notes=[]
    for name,repo in SOURCES.items():
        store=GitStore(repo);sha=store.resolve('HEAD');files=store.snapshot(sha,Config());choice=None
        for path,text in sorted(files.items()):
            if not path.endswith('.py'):continue
            try:units=parse_python(path,text)
            except DocMendError:continue
            for unit in units:
                if unit.kind!='function' or '.' in unit.name:continue
                tree=ast.parse(unit.source);node=next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)))
                args=node.args.posonlyargs+node.args.args
                defaults={a.arg:v for a,v in zip(args[len(args)-len(node.args.defaults):],node.args.defaults)}
                defaults.update({a.arg:v for a,v in zip(node.args.kwonlyargs,node.args.kw_defaults) if v is not None})
                for key,value in defaults.items():
                    try:number=ast.literal_eval(value)
                    except (ValueError,TypeError,SyntaxError):continue
                    if type(number) is int and 0<number<1000:choice=(path,text,unit,node,key,value,number);break
                if choice:break
            if choice:break
        if choice is None:raise RuntimeError('No suitable function in '+name)
        path,fulltext,unit,node,key,value,number=choice
        lines=unit.source.splitlines(keepends=True);line=lines[value.lineno-1].encode();lines[value.lineno-1]=(line[:value.col_offset]+str(number+1).encode()+line[value.end_col_offset:]).decode();changed=''.join(lines)
        newunit=parse_python(path,changed)[0]
        doc='# API\n\nSignature: `'+unit.facts['signature']+'`.\n';newdoc='# API\n\nSignature: `'+newunit.facts['signature']+'`.\n'
        provenance={'kind':'source-backed-controlled-mutation','repository_name':name,'source_commit':sha,'source_path':path,'source_unit':unit.id,'full_source_file_sha256':hashlib.sha256(fulltext.encode()).hexdigest(),'snippet_sha256':hashlib.sha256(unit.source.encode()).hexdigest(),'source_lines':[unit.line,unit.end_line],'documentation':'Constructed exact-signature declaration, not pre-existing natural documentation','label_author':'AI-assisted construction; not independently human reviewed','natural_repository_history':False}
        variants=[('changed-default',changed,doc,True,newdoc,'Declared numeric default changed.'),('docs-updated',changed,newdoc,False,newdoc,'Declaration updated together with source.'),('comment-only','# Additional comment.\n'+unit.source,doc,False,doc,'Only a source comment changed.'),('removed-function','',doc,True,'# API\n\nThe '+unit.name+' function was removed.\n','Advertised function no longer exists.')]
        for label,after,adoc,stale,gold,rationale in variants:
            cases.append({'id':name+'-'+label,'split':'source-backed','family':label,'before':{path:unit.source,'README.md':doc},'after':{path:after,'README.md':adoc},'labels':[{'path':'README.md','heading':'API','stale':stale,'rationale':rationale}],'gold_files':{'README.md':gold},'provenance':provenance})
        source_notes.append(provenance)
    output.write_text(''.join(json.dumps(c,ensure_ascii=False,sort_keys=True)+'\n' for c in cases))
    (ROOT/'evals/source-manifest.json').write_text(json.dumps({'case_count':len(cases),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'sources':source_notes,'scope':'Isolated actual function snippets with controlled changes and constructed docs, not full-repository natural-history accuracy.'},indent=2)+'\n')
    print(json.dumps({'cases':len(cases),'sources':source_notes},indent=2))
if __name__=='__main__':main()
