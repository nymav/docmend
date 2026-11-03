"""Prepare historical snapshots for independent annotation, then score reviewed cases.

Reviewer declarations are recorded evidence, not independently verified identities.
"""
import json
from pathlib import Path
from .config import Config
from .docparse import parse_docs
from .evaluation import load_cases, evaluate, release_gates
from .models import DocMendError, digest


def prepare(store, base, head, author):
    if not author.strip(): raise DocMendError('Dataset preparer name is required')
    base,head=store.resolve(base),store.resolve(head)
    cfg=store.trusted_config(base)
    before,after=store.snapshot(base,cfg),store.snapshot(head,cfg)
    sections=parse_docs(after)
    labels=[{'path':s.path,'heading':s.heading,'stale':None,'rationale':''} for s in sections.values()]
    if not labels:raise DocMendError('No documentation sections to annotate')
    if len({(s['path'],s['heading']) for s in labels})!=len(labels):raise DocMendError('Disambiguate duplicate section headings before annotation')
    fingerprint=digest(json.dumps({'before':before,'after':after},sort_keys=True))
    return {'id':head[:12]+'-'+base[:12],'family':'historical','before':before,'after':after,'gold_files':{},'labels':labels,'analysis_patterns':{'include':list(cfg.include),'exclude':list(cfg.exclude)},
            'provenance':{'kind':'historical-snapshot','base':base,'head':head,'prepared_by':author,'input_sha256':fingerprint,'patterns_sha256':digest(json.dumps({'include':list(cfg.include),'exclude':list(cfg.exclude)},sort_keys=True))},'reviews':[]}


def reviewed_cases(path: Path):
    cases=load_cases(path)
    for case in cases:
        provenance=case.get('provenance',{})
        if provenance.get('kind')!='historical-snapshot' or provenance.get('input_sha256')!=case['input_sha256']:
            raise DocMendError('Historical provenance is missing or snapshots changed after preparation')
        if provenance.get('patterns_sha256')!=digest(json.dumps(case.get('analysis_patterns'),sort_keys=True)):
            raise DocMendError('Analysis patterns changed after benchmark preparation')
        author=provenance.get('prepared_by','').strip().casefold()
        reviews=case.get('reviews',[])
        expected=sorted(case['labels'],key=lambda x:(x['path'],x['heading']))
        people=set()
        for review in reviews:
            name=review.get('reviewer','').strip().casefold()
            if not name or name==author or name in people:raise DocMendError('Two distinct reviewers other than the preparer are required')
            people.add(name)
            if review.get('input_sha256')!=case['input_sha256'] or sorted(review.get('labels',[]),key=lambda x:(x['path'],x['heading']))!=expected:
                raise DocMendError('Reviewer labels must agree with the adjudicated labels and immutable inputs')
        if len(people)<2:raise DocMendError('Two independent reviewer declarations are required')
        # Every stale section needs an exact gold correction, including deferred cases.
        gold={(s.path,s.heading) for s in parse_docs(case['gold_files']).values()}
        if any(label['stale'] and (label['path'],label['heading']) not in gold for label in case['labels']):
            raise DocMendError('Gold documentation is required for each stale section')
    truths={label['stale'] for case in cases for label in case['labels']}
    if truths!={True,False}:raise DocMendError('Reviewed benchmark must include both stale and accurate sections')
    return cases


def score_reviewed(path: Path):
    cases=reviewed_cases(path)
    result=evaluate(cases)
    result.update({'dataset_sha256':digest(path.read_text()),'cases':len(cases),'reviewer_identity_verification':'self-declared; not verified by DocMend','release_gates':release_gates(result)})
    return result
