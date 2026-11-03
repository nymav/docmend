"""GitHub Docker Action entrypoint; argument vectors, not interpolated shell code."""
import json
import os
from pathlib import Path
import sys
from docmend.cli import main


def truth(name):
    value=os.environ.get('INPUT_'+name,'false').lower()
    if value not in ('true','false'):
        raise ValueError(name+' must be true or false')
    return value=='true'


def run():
    event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    pr=event.get('pull_request',{})
    head_repo=pr.get('head',{}).get('repo',{})
    base_repo=pr.get('base',{}).get('repo',{})
    fork=bool(head_repo.get('fork')) or bool(head_repo.get('full_name') and base_repo.get('full_name') and head_repo['full_name']!=base_repo['full_name'])
    llm,semantic,publish=truth('LLM'),truth('SEMANTIC'),truth('PUBLISH')
    if os.environ.get('GITHUB_EVENT_NAME')=='pull_request_target':
        raise ValueError('pull_request_target is intentionally unsupported')
    if fork and (llm or semantic or publish):
        raise ValueError('Fork PRs support offline read-only analysis only')
    base=os.environ.get('INPUT_BASE') or pr.get('base',{}).get('sha')
    head=os.environ.get('INPUT_HEAD') or pr.get('head',{}).get('sha') or 'HEAD'
    if not base:raise ValueError('base commit is required outside pull_request events')
    repo=Path(os.environ.get('GITHUB_WORKSPACE','.')).resolve()
    out=os.environ.get('INPUT_OUTPUT','docmend-report')
    fail=os.environ.get('INPUT_FAIL-ON','review')
    if fail not in ('review','stale','never'):raise ValueError('fail-on must be review, stale, or never')
    if '\n' in out or '\r' in out:raise ValueError('output path must be one line')
    args=['check','--repo',str(repo),'--base',base,'--head',head,'--output',out,'--fail-on',fail]
    if llm or semantic:
        # The committed config may name only this fixed action-secret environment.
        os.environ['DOCMEND_API_KEY']=os.environ.get('INPUT_LLM-API-KEY','')
    if llm:args+=['--llm']
    if semantic:args+=['--semantic']
    result=main(args)
    if result not in (0,2):return result
    report=json.loads((repo/out/'report.json').read_text())
    output=os.environ.get('GITHUB_OUTPUT')
    if output:
        # Restrict path to one line; never pass repository data as workflow commands.
        if '\n' in out or '\r' in out:raise ValueError('output path must be one line')
        with open(output,'a') as f:
            f.write('report='+out+'/report.json\n')
            f.write('sarif='+out+'/report.sarif\n')
            for name,value in [('stale',sum(x['status']=='stale' for x in report['findings'])),('review',sum(x['status']=='review' for x in report['findings'])),('safe-edits',sum(x['mode']=='safe' for x in report['edits']))]:f.write(f'{name}={value}\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write((repo/out/'summary.md').read_text())
    if publish:
        if not pr.get('number'):raise ValueError('publish requires a PR event')
        os.environ['DOCMEND_BOT_LOGIN']=os.environ.get('INPUT_BOT-LOGIN','github-actions[bot]')
        os.environ['DOCMEND_GITHUB_TOKEN']=os.environ.get('INPUT_GITHUB-TOKEN','')
        args=['publish','--repo',str(repo),'--base',base,'--head',head,'--output',out,'--repository',os.environ['GITHUB_REPOSITORY'],'--pr',str(pr['number'])]
        if llm:args+=['--llm']
        if semantic:args+=['--semantic']
        publish_result=main(args)
        if publish_result:return publish_result
    return result


if __name__=='__main__':
    try:sys.exit(run())
    except (ValueError,KeyError,OSError) as exc:
        print(json.dumps({'error':str(exc)}),file=sys.stderr);sys.exit(3)
