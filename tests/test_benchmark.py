import json,tempfile,unittest
from pathlib import Path
from docmend.benchmark import prepare,reviewed_cases,score_reviewed
from docmend.gitstore import GitStore
from docmend.models import DocMendError
from test_core import fixture

class BenchmarkTests(unittest.TestCase):
    def case(self,root):
        base,head=fixture(root)
        return prepare(GitStore(Path(root)),base,head,'Fixture preparer')
    def annotate(self,case):
        # Synthetic reviewer declarations test the contract, not actual human review.
        for label in case['labels']:
            label['stale']=label['heading']=='API';label['rationale']='Synthetic test assertion'
        case['gold_files']={**case['after'],'docs/api.md':case['after']['docs/api.md'].replace('timeout=30','timeout=60')}
        case['reviews']=[{'reviewer':name,'input_sha256':case['provenance']['input_sha256'],'labels':case['labels']} for name in ('Fixture reviewer A','Fixture reviewer B')]
        return case
    def test_unreviewed_data_refused_and_inputs_frozen(self):
        with tempfile.TemporaryDirectory() as td:
            case=self.case(td);path=Path(td)/'cases.jsonl';path.write_text(json.dumps(case)+'\n')
            with self.assertRaises(DocMendError):reviewed_cases(path)
            case=self.annotate(case);path.write_text(json.dumps(case)+'\n')
            self.assertEqual(len(reviewed_cases(path)),1)
            result=score_reviewed(path)
            self.assertEqual(result['cases'],1)
            case['after']['api.py']+='\n# modified\n';path.write_text(json.dumps(case)+'\n')
            with self.assertRaises(DocMendError):reviewed_cases(path)
    def test_distinct_reviewers_and_agreement_required(self):
        with tempfile.TemporaryDirectory() as td:
            case=self.annotate(self.case(td));path=Path(td)/'cases.jsonl'
            case['reviews'][1]['reviewer']=case['reviews'][0]['reviewer'];path.write_text(json.dumps(case)+'\n')
            with self.assertRaises(DocMendError):reviewed_cases(path)
            case['reviews'][1]['reviewer']='Other';case['reviews'][1]['input_sha256']='changed';path.write_text(json.dumps(case)+'\n')
            with self.assertRaises(DocMendError):reviewed_cases(path)
