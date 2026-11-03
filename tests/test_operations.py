import io,json,os,tempfile,unittest
from unittest.mock import patch,Mock
from docmend.budget import Budget
from docmend.config import Config
from docmend.models import DocMendError
from docmend.provider import ModelProvider
from docmend.operations import validate_installation

class OperationsTests(unittest.TestCase):
    def test_deadline_expiry(self):
        with patch('docmend.budget.time.monotonic',side_effect=[10,12]):
            b=Budget(1)
            with self.assertRaises(DocMendError):b.remaining()
    def test_request_count_and_timeout_bounded(self):
        with patch.dict(os.environ,{'DOCMEND_API_KEY':'fictional-secret'}):
            p=ModelProvider(Config(endpoint='https://provider.invalid',model='probe',max_provider_requests=1))
        with patch.object(p.opener,'open',return_value=io.BytesIO(b'{}')) as opened:
            p.request('/chat/completions',{})
            self.assertLessEqual(opened.call_args.kwargs['timeout'],30)
            with self.assertRaises(DocMendError):p.request('/chat/completions',{})
            self.assertEqual(opened.call_count,1)
    def test_app_repository_access_and_redaction(self):
        opener=Mock();opener.open.return_value=io.BytesIO(json.dumps({'repositories':[{'full_name':'owner/repo'}]}).encode())
        result=validate_installation('owner/repo','fictional-secret',opener=opener)
        self.assertEqual(result['mutations'],0)
        self.assertNotIn('fictional-secret',json.dumps(result))
        opener.open.return_value=io.BytesIO(b'{}')
        with self.assertRaises(DocMendError):validate_installation('owner/repo','fictional-secret',opener=opener)
    def test_budget_config_bounds(self):
        for text in ('analysis_timeout_seconds = 0','max_provider_requests = 501'):
            with self.assertRaises(DocMendError):Config.from_text(text)
    def test_pipeline_aborts_expired_budget(self):
        from docmend.pipeline import analyze_files
        from test_core import BEFORE,AFTER
        budget=Mock();budget.remaining.side_effect=[1,DocMendError('expired')]
        with self.assertRaises(DocMendError):analyze_files(BEFORE,AFTER,budget=budget)
