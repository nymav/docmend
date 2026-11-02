"""Section-level evaluation with explicit abstentions, gold repairs and baselines."""
from __future__ import annotations

from collections import Counter,defaultdict
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

from .changes import classify
from .codeparse import parse_code
from .config import Config
from .docparse import parse_docs
from .mapping import build_index
from .models import DocMendError
from .pipeline import analyze_files
from .repair import patched_files


METHODS=('changed-file','changed-reference','docmend')

def ratio(numerator,denominator):
    return numerator/denominator if denominator else None


def wilson(successes,total):
    if not total:return None
    z=1.959963984540054;p=successes/total;den=1+z*z/total
    center=(p+z*z/(2*total))/den
    radius=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [max(0,center-radius),min(1,center+radius)]


def load_cases(path: Path):
    result=[];ids=set();fingerprints=set()
    for number,line in enumerate(path.read_text().splitlines(),1):
        if not line.strip():continue
        try:c=json.loads(line)
        except ValueError as e:raise DocMendError(f'Invalid JSONL line {number}') from e
        if not isinstance(c,dict) or not isinstance(c.get('id'),str) or c['id'] in ids:
            raise DocMendError('Missing/duplicate case identifier')
        for key in ('before','after','gold_files'):
            if not isinstance(c.get(key),dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in c[key].items()):raise DocMendError('Case file maps must contain text')
        cfg=Config();after={p:t for p,t in c['after'].items() if cfg.accepts(p)};sections=parse_docs(after)
        available={(s.path,s.heading) for s in sections.values()}
        labels=c.get('labels')
        if not isinstance(labels,list) or not labels:raise DocMendError('Each case needs explicit section labels')
        labelled=[]
        for label in labels:
            if not isinstance(label,dict) or type(label.get('stale')) is not bool or not label.get('rationale'):raise DocMendError('Labels need boolean truth and rationale')
            key=(label.get('path'),label.get('heading'));labelled.append(key)
            if key not in available:raise DocMendError('Label points outside the after-snapshot sections')
        if set(labelled)!=available or len(labelled)!=len(set(labelled)):raise DocMendError('Label every section exactly once; duplicate headings need unique paths')
        fingerprint=hashlib.sha256(json.dumps({'before':c['before'],'after':c['after']},sort_keys=True).encode()).hexdigest()
        if fingerprint in fingerprints:raise DocMendError('Duplicate before/after input pair')
        ids.add(c['id']);fingerprints.add(fingerprint);c['input_sha256']=fingerprint;result.append(c)
    return result


def assert_disjoint(left,right):
    if {c['id'] for c in left}&{c['id'] for c in right}:raise DocMendError('Split identifier overlap')
    if {c['input_sha256'] for c in left}&{c['input_sha256'] for c in right}:raise DocMendError('Identical input pair occurs in both splits')


def predict(case,method):
    if method not in METHODS:raise DocMendError('Unknown evaluation method')
    cfg=Config();before={p:t for p,t in case['before'].items() if cfg.accepts(p)};after={p:t for p,t in case['after'].items() if cfg.accepts(p)}
    sections=parse_docs(after)
    if method=='docmend':
        report,index=analyze_files(before,after)
        states={s.id:'none' for s in sections.values()};states.update({f.section_id:f.status for f in report.findings})
        return states,report.edits,patched_files(after,report.edits),report.warnings
    old,new=parse_code(before),parse_code(after)
    changed=classify(old,new)
    if method=='changed-file':
        any_code_change=any(before.get(p)!=after.get(p) for p in before.keys()|after.keys() if p.endswith(('.py','.toml')))
        return {s.id:'stale' if any_code_change else 'none' for s in sections.values()},[],{},[]
    linked=set()
    old_docs=parse_docs(before)
    for graph in [build_index(old,old_docs),build_index(new,sections)]:
        changed_ids={c.unit.id for c in changed}
        linked.update(e['section'] for e in graph['links'] if e['unit'] in changed_ids)
    return {s.id:'stale' if s.id in linked else 'none' for s in sections.values()},[],{},[]


def aggregate(outcomes,latencies):
    cm=Counter();review=0;triaged_positive=0;decisions=0;decision_correct=0
    proposed=correct=unsafe=untouched=preserved=errors=0
    for o in outcomes:
        gold=o['gold_stale'];status=o['status'];pred=status=='stale'
        cm['tp' if pred and gold else 'fp' if pred else 'fn' if gold else 'tn']+=1
        review+=status=='review'
        triaged_positive+=gold and status in ('stale','review')
        if status not in ('review','error'):
            decisions+=1;decision_correct+=pred==gold
        errors+=status=='error';proposed+=o['safe_repairs'];correct+=o['correct_repairs'];unsafe+=o['incorrect_repairs']
        if not gold:untouched+=1;preserved+=not o['documentation_changed']
    total=len(outcomes);positives=cm['tp']+cm['fn']
    return {'sections':total,'positive_sections':positives,'negative_sections':total-positives,**{k:cm[k] for k in ('tp','fp','fn','tn')},'confirmed_precision':ratio(cm['tp'],cm['tp']+cm['fp']),'confirmed_recall':ratio(cm['tp'],positives),'precision_wilson_95':wilson(cm['tp'],cm['tp']+cm['fp']),'recall_wilson_95':wilson(cm['tp'],positives),'triage_recall':ratio(triaged_positive,positives),'review_sections':review,'review_rate':ratio(review,total),'decision_coverage':ratio(decisions,total),'selective_accuracy':ratio(decision_correct,decisions),'proposed_safe_repairs':proposed,'correct_repairs':correct,'incorrect_repairs':unsafe,'repair_exact_match':ratio(correct,proposed),'repair_wilson_95':wilson(correct,proposed),'negative_section_preservation':ratio(preserved,untouched),'operational_error_sections':errors,'latency_ms_median':statistics.median(latencies) if latencies else None,'latency_ms_p95':sorted(latencies)[max(0,math.ceil(.95*len(latencies))-1)] if latencies else None}


def evaluate(cases,*,repeats=3):
    if type(repeats) is not int or not 1<=repeats<=20:raise DocMendError('Repeat count must be 1..20')
    all_results={};raw={}
    for method in METHODS:
        outcomes=[];latencies=[]
        for c in cases:
            cfg=Config();after={p:t for p,t in c['after'].items() if cfg.accepts(p)};sections=parse_docs(after)
            truth={(x['path'],x['heading']):x for x in c['labels']}
            gold_sections=parse_docs({p:t for p,t in c['gold_files'].items() if p.endswith(('.md','.mdx'))})
            gold_by_key={(s.path,s.heading):s.text for s in gold_sections.values()}
            try:
                # Timed repeated calls are not model repeats or a production load test.
                for repeat in range(repeats):
                    start=time.perf_counter();states,edits,updated,warnings=predict(c,method);latencies.append((time.perf_counter()-start)*1000)
            except (DocMendError,ValueError,TypeError) as exc:
                states={s.id:'error' for s in sections.values()};edits=[];updated={};warnings=[str(exc)]
            for sid,section in sections.items():
                label=truth[(section.path,section.heading)]
                proposed=[e for e in edits if e.section_id==sid and e.mode=='safe']
                expected=gold_by_key.get((section.path,section.heading))
                correct=sum(expected is not None and e.after==expected and label['stale'] for e in proposed)
                changed=updated.get(section.path,after[section.path])!=after[section.path]
                # For multi-section files, compare this section's text, not the whole file.
                new_sections=parse_docs({section.path:updated.get(section.path,after[section.path])})
                new_by_heading={s.heading:s.text for s in new_sections.values()}
                changed=new_by_heading.get(section.heading)!=section.text
                outcomes.append({'case':c['id'],'family':c['family'],'section_id':sid,'input_sha256':c['input_sha256'],'gold_stale':label['stale'],'status':states.get(sid,'none'),'safe_repairs':len(proposed),'correct_repairs':correct,'incorrect_repairs':len(proposed)-correct,'documentation_changed':changed,'warnings':warnings,'rationale':label['rationale']})
        families={}
        for family in sorted({o['family'] for o in outcomes}):families[family]=aggregate([o for o in outcomes if o['family']==family],[])
        all_results[method]={'overall':aggregate(outcomes,latencies),'by_family':families};raw[method]=outcomes
    return {'methods':all_results,'outcomes':raw,'timing_repeats':repeats,'scoring':'Primary recall treats review/error as missed confirmed detections. Triage recall also credits review. Selective accuracy excludes review/error. Repair quality uses exact gold-section text; null means no proposals, not perfect quality. Wilson intervals treat sections as independent and are descriptive for these constructed fixtures.'}


def report_markdown(result,title):
    def fmt(v):return '—' if v is None else f'{v:.1%}'
    out=['# '+title,'','| Method | Precision | Confirmed recall | Triage recall | Review burden | Repair correctness | Negative preservation |','|---|---:|---:|---:|---:|---:|---:|']
    for name,r in result['methods'].items():
        m=r['overall'];out.append('| '+name+' | '+' | '.join(fmt(m[k]) for k in ['confirmed_precision','confirmed_recall','triage_recall','review_rate','repair_exact_match','negative_section_preservation'])+' |')
    out+=['','## Interpretation','',result['scoring'],'','## Case-level results','','| Case | Truth | DocMend decision | Safe / correct repairs |','|---|---|---|---|']
    for o in result['outcomes']['docmend']:out.append(f'| {o["case"]} | {"stale" if o["gold_stale"] else "accurate"} | {o["status"]} | {o["safe_repairs"]} / {o["correct_repairs"]} |')
    out+=['','## Limits','','Cases and labels are AI-authored constructed examples unless provenance explicitly states a real source snapshot. Source-backed mutation cases still use constructed documentation/changes. They are not natural historical documentation bugs or independently human-reviewed ground truth. No paid model was evaluated. Timing is warm local sequential execution, not concurrent-load performance.','']
    return '\n'.join(out)
