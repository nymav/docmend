"""Historical benchmark preparation and independently reviewed scoring (no model calls)."""
import argparse,json
from pathlib import Path
from docmend.benchmark import prepare,score_reviewed
from docmend.gitstore import GitStore

def main():
    p=argparse.ArgumentParser();subs=p.add_subparsers(dest='command',required=True)
    a=subs.add_parser('prepare');a.add_argument('--repo',type=Path,required=True);a.add_argument('--base',required=True);a.add_argument('--head',required=True);a.add_argument('--author',required=True)
    a.add_argument('--output',type=Path,required=True)
    b=subs.add_parser('score');b.add_argument('--dataset',type=Path,required=True);b.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=prepare(GitStore(args.repo),args.base,args.head,args.author) if args.command=='prepare' else score_reviewed(args.dataset)
    # Exclusive create: do not overwrite reviewers' work or previous results.
    with args.output.open('x') as stream:stream.write(json.dumps(result)+'\n' if args.command=='prepare' else json.dumps(result,indent=2)+'\n')
    return 0 if args.command=='prepare' or result['release_gates']['passed'] else 2
if __name__=='__main__':raise SystemExit(main())
