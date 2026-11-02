"""Score frozen inputs; save actual software/data fingerprints and all case outcomes."""
import argparse,hashlib,json,platform,subprocess
from pathlib import Path
from docmend.evaluation import load_cases,assert_disjoint,evaluate,report_markdown

def main():
    p=argparse.ArgumentParser();p.add_argument('--split',choices=['development','challenge','source-backed'],required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--repeats',type=int,default=3);args=p.parse_args()
    root=Path(__file__).resolve().parents[1];data=root/'evals'/(args.split+'.jsonl');manifest=json.loads((root/'evals/manifest.json').read_text())
    if args.split in manifest['splits']:
        assert hashlib.sha256(data.read_bytes()).hexdigest()==manifest['splits'][args.split]['sha256'],'Frozen data changed'
    cases=load_cases(data)
    if args.split in ('development','challenge'):assert_disjoint(load_cases(root/'evals/development.jsonl'),load_cases(root/'evals/challenge.jsonl'))
    result=evaluate(cases,repeats=args.repeats)
    digest=hashlib.sha256()
    for f in sorted((root/'src/docmend').glob('*.py')):digest.update(f.name.encode()+b'\0'+f.read_bytes())
    result.update({'split':args.split,'cases':len(cases),'dataset_sha256':hashlib.sha256(data.read_bytes()).hexdigest(),'software_source_sha256':digest.hexdigest(),'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root).decode().strip(),'python':platform.python_version(),'provider_calls':0})
    args.output.mkdir(parents=True,exist_ok=True);(args.output/'results.json').write_text(json.dumps(result,indent=2)+'\n');(args.output/'REPORT.md').write_text(report_markdown(result,args.split+' evaluation'))
    print(json.dumps({m:r['overall'] for m,r in result['methods'].items()},indent=2))
if __name__=='__main__':main()
