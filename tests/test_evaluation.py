import copy
import json
from pathlib import Path
import tempfile
import unittest

from docmend.evaluation import METHODS,aggregate,assert_disjoint,evaluate,load_cases,predict,ratio,wilson
from docmend.models import DocMendError
from docmend.pipeline import analyze_files

ROOT=Path(__file__).resolve().parents[1]
B='def fetch(timeout=30):\n    return 1\n';A=B.replace('30','60')

def outcome(gold,status,**extra):
    return {'gold_stale':gold,'status':status,'safe_repairs':0,'correct_repairs':0,'incorrect_repairs':0,'documentation_changed':False,**extra}

class HistoricalRepairTests(unittest.TestCase):
    def inspect(self,text,heading='API'):
        doc=f'# {heading}\n\n'+text+'\n';return analyze_files({'a.py':B,'a.md':doc},{'a.py':A,'a.md':doc})[0]
    def test_previous_signature_is_preserved(self):self.assertFalse(self.inspect('Previous signature: `fetch(timeout=30)`.').edits)
    def test_old_signature_is_preserved(self):self.assertFalse(self.inspect('Old signature: `fetch(timeout=30)`.').edits)
    def test_hidden_multiline_comment_is_preserved(self):self.assertFalse(self.inspect('<!--\nSignature: `fetch(timeout=30)`.\n-->').edits)
    def test_hidden_single_line_is_preserved(self):self.assertFalse(self.inspect('<!-- Signature: `fetch(timeout=30)`. -->').edits)
    def test_unclosed_comment_is_not_rewritten(self):self.assertFalse(self.inspect('<!--\nSignature: `fetch(timeout=30)`.').edits)
    def test_changelog_declaration_is_preserved(self):self.assertFalse(self.inspect('Signature: `fetch(timeout=30)`.','Changelog').edits)
    def test_comment_then_public_declaration(self):
        r=self.inspect('<!-- obsolete material -->\nSignature: `fetch(timeout=30)`.');self.assertEqual(len(r.edits),1)
    def test_current_signature_still_repaired(self):self.assertEqual(len(self.inspect('Signature: `fetch(timeout=30)`.').edits),1)

class MetricTests(unittest.TestCase):
    def test_review_is_not_confirmed_true_positive(self):
        x=aggregate([outcome(True,'review')],[]);self.assertEqual(x['confirmed_recall'],0);self.assertEqual(x['triage_recall'],1);self.assertEqual(x['review_rate'],1);self.assertIsNone(x['selective_accuracy'])
    def test_zero_proposals_is_not_perfect_repair_quality(self):self.assertIsNone(aggregate([outcome(False,'none')],[])['repair_exact_match'])
    def test_wrong_repair_and_false_alarm_count(self):
        x=aggregate([outcome(False,'stale',safe_repairs=1,incorrect_repairs=1,documentation_changed=True)],[])
        self.assertEqual(x['fp'],1);self.assertEqual(x['repair_exact_match'],0);self.assertEqual(x['negative_section_preservation'],0)
    def test_confusion_and_selective_denominators(self):
        x=aggregate([outcome(True,'stale'),outcome(True,'none'),outcome(False,'stale'),outcome(False,'none'),outcome(True,'review')],[])
        self.assertEqual((x['tp'],x['fp'],x['fn'],x['tn']),(1,1,2,1));self.assertAlmostEqual(x['confirmed_precision'],.5);self.assertAlmostEqual(x['confirmed_recall'],1/3);self.assertEqual(x['decision_coverage'],.8)
    def test_error_stays_in_recall_denominator(self):
        x=aggregate([outcome(True,'error')],[]);self.assertEqual(x['fn'],1);self.assertEqual(x['operational_error_sections'],1);self.assertEqual(x['decision_coverage'],0)
    def test_confidence_interval_and_null(self):
        lo,hi=wilson(1,1);self.assertLess(lo,1);self.assertEqual(hi,1);self.assertIsNone(wilson(0,0));self.assertIsNone(ratio(0,0))
    def test_p95_uses_nearest_rank(self):self.assertEqual(aggregate([],list(range(1,21)))['latency_ms_p95'],19)

class DatasetTests(unittest.TestCase):
    def test_development_manifest_and_unique_inputs(self):
        cases=load_cases(ROOT/'evals/development.jsonl');self.assertEqual(len(cases),28);self.assertEqual(len({c['input_sha256'] for c in cases}),28)
    def test_disjoint_rejects_input_leakage(self):
        cases=load_cases(ROOT/'evals/development.jsonl');other=copy.deepcopy(cases[:1]);other[0]['id']='new-id'
        with self.assertRaises(DocMendError):assert_disjoint(cases,other)
    def test_unknown_method_fails(self):
        c=load_cases(ROOT/'evals/development.jsonl')[0]
        with self.assertRaises(DocMendError):predict(c,'imaginary')
    def test_gold_labels_must_cover_sections(self):
        c=copy.deepcopy(load_cases(ROOT/'evals/development.jsonl')[0]);c['labels'][0]['heading']='missing'
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bad.jsonl';p.write_text(json.dumps(c)+'\n')
            with self.assertRaises(DocMendError):load_cases(p)
    def test_repeated_scoring_has_fixed_outcomes(self):
        c=load_cases(ROOT/'evals/development.jsonl')[:2];a=evaluate(c,repeats=1);b=evaluate(c,repeats=2)
        for m in METHODS:self.assertEqual(a['outcomes'][m],b['outcomes'][m])
