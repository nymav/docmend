import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from docmend.config import Config
from docmend.models import DocMendError
from docmend.provider import ModelProvider, NoRedirect
from test_core import fixture

class HttpTests(unittest.TestCase):
    def provider(self):
        with patch.dict(os.environ,{'DOCMEND_API_KEY':'unit-test-secret'}):return ModelProvider(Config(endpoint='https://provider.invalid/v1',model='test'))
    def test_chat_transport_payload_and_secret_redaction(self):
        p=self.provider()
        answer={'choices':[{'message':{'content':json.dumps({'status':'accurate'})}}]}
        response=io.BytesIO(json.dumps(answer).encode())
        with patch.object(p.opener,'open',return_value=response) as op:
            self.assertEqual(p.json('Return JSON',{'doc':'evidence'}),{'status':'accurate'})
            request=op.call_args.args[0];body=json.loads(request.data)
            self.assertIn('untrusted',body['messages'][0]['content'])
            self.assertNotIn('unit-test-secret',request.data.decode())
    def test_bounded_rate_limit_retries(self):
        p=self.provider();error=HTTPError('https://provider.invalid',429,'limited',{},None)
        with patch.object(p.opener,'open',side_effect=error) as op,patch('docmend.provider.time.sleep') as sleep:
            with self.assertRaises(DocMendError) as e:p.request('/chat/completions',{})
            self.assertEqual(op.call_count,3);self.assertEqual(sleep.call_count,2);self.assertNotIn('unit-test-secret',str(e.exception))
    def test_bad_json_and_context_budget(self):
        p=self.provider()
        with patch.object(p.opener,'open',return_value=io.BytesIO(b'not JSON')):
            with self.assertRaises(DocMendError):p.request('/chat/completions',{})
        with self.assertRaises(DocMendError):p.json('Return JSON',{'x':'a'*30000})
    def test_redirects_refused(self):
        with self.assertRaises(DocMendError):NoRedirect().redirect_request(None,None,302,'',{},'https://attacker.invalid')
    def test_embeddings_wrong_indices_rejected(self):
        p=self.provider();p.cfg=Config(endpoint='https://provider.invalid/v1',model='test',embedding_model='embed')
        with patch.object(p,'request',return_value={'data':[{'index':5,'embedding':[1.,0.]}]}):
            with self.assertRaises(DocMendError):p.embed(['text'])

spec=importlib.util.spec_from_file_location('action_entry',Path(__file__).resolve().parents[1]/'entrypoint.py');entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
class ActionTests(unittest.TestCase):
    def test_fork_secrets_and_target_event_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'event.json';p.write_text(json.dumps({'pull_request':{'head':{'repo':{'fork':True}}}}))
            env={'GITHUB_EVENT_PATH':str(p),'INPUT_LLM':'true'}
            with patch.dict(os.environ,env,clear=True):
                with self.assertRaises(ValueError):entry.run()
            with patch.dict(os.environ,{**env,'INPUT_LLM':'false','GITHUB_EVENT_NAME':'pull_request_target'},clear=True):
                with self.assertRaises(ValueError):entry.run()
    def test_full_entrypoint_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            base,head=fixture(td);root=Path(td);event=root/'event.json';event.write_text(json.dumps({'pull_request':{'head':{'sha':head,'repo':{'fork':False}},'base':{'sha':base}}}))
            env={'GITHUB_EVENT_PATH':str(event),'GITHUB_WORKSPACE':td,'GITHUB_OUTPUT':str(root/'output.txt'),'GITHUB_STEP_SUMMARY':str(root/'summary.md')}
            with patch.dict(os.environ,env,clear=True),patch('sys.stdout',new_callable=io.StringIO):self.assertEqual(entry.run(),2)
            self.assertIn('safe-edits=1',(root/'output.txt').read_text());self.assertIn('DocMend',(root/'summary.md').read_text())
