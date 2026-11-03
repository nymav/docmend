from dataclasses import replace
import unittest
from unittest.mock import patch
from docmend.github import GitHub
from docmend.models import DocMendError
from docmend.pipeline import analyze_files
from test_core import BEFORE, AFTER

class PublishTests(unittest.TestCase):
    def test_stale_head_and_fork_rejected_before_writes(self):
        r,_=analyze_files(BEFORE,AFTER,base='b'*40,head='a'*40)
        for repo,head in [('fork/repo',r.head),('owner/repo','changed')]:
            pull={'state':'open','head':{'repo':{'full_name':repo},'sha':head},'base':{'repo':{'full_name':'owner/repo'},'sha':r.base}}
            client=GitHub('owner/repo','token')
            with patch.object(client,'request',return_value=pull) as request:
                with self.assertRaises(DocMendError):client.publish(3,r,AFTER)
                self.assertEqual(request.call_count,1)

    def test_branch_pr_and_summary_idempotent(self):
        r,_=analyze_files(BEFORE,AFTER,base='b'*40,head='a'*40)
        pull={'state':'open','head':{'repo':{'full_name':'owner/repo'},'sha':r.head,'ref':'feature'},'base':{'repo':{'full_name':'owner/repo'},'sha':r.base}}
        state={'branch':None,'pr':None,'comments':[]};calls=[];client=GitHub('owner/repo','token')
        def request(method,path,body=None):
            calls.append((method,path,body))
            if path=='/pulls/3':return pull
            if path=='/git/commits/'+r.head:return {'tree':{'sha':'parent-tree'}}
            if path=='/git/trees':return {'sha':'new-tree'}
            if path.startswith('/git/matching-refs'):return [] if state['branch'] is None else [state['branch']]
            if path=='/git/commits/new-commit':return {'tree':{'sha':'new-tree'},'parents':[{'sha':r.head}]}
            if path=='/git/commits':return {'sha':'new-commit'}
            if path=='/git/refs':state['branch']={'ref':body['ref'],'object':{'sha':body['sha']}};return state['branch']
            if path.startswith('/pulls?'):return [] if state['pr'] is None else [state['pr']]
            if path=='/pulls':
                self.assertTrue(body['draft']);self.assertEqual(body['base'],'feature');state['pr']={'html_url':'https://github.com/owner/repo/pull/4'};return state['pr']
            if path.startswith('/issues/3/comments?'):return state['comments']
            if path=='/issues/3/comments':state['comments']=[{'id':9,'body':body['body'],'user':{'type':'Bot','login':'github-actions[bot]'}}];return {'html_url':'summary'}
            if path=='/issues/comments/9':return {'html_url':'summary'}
            raise AssertionError(path)
        with patch.object(client,'request',side_effect=request):
            self.assertEqual(client.publish(3,r,AFTER),client.publish(3,r,AFTER))
        for route in ['/git/refs','/pulls','/issues/3/comments']:
            self.assertEqual(sum(method=='POST' and path==route for method,path,body in calls),1)

    def test_model_drafts_not_published_by_default(self):
        r,_=analyze_files(BEFORE,AFTER,base='b'*40,head='a'*40);r.edits=[replace(r.edits[0],mode='draft',evidence='model')]
        client=GitHub('owner/repo','token');calls=[]
        def request(method,path,body=None):
            calls.append(path)
            if path=='/pulls/1':return {'state':'open','head':{'repo':{'full_name':'owner/repo'},'sha':r.head},'base':{'repo':{'full_name':'owner/repo'},'sha':r.base}}
            if path.startswith('/issues/1/comments?'):return []
            if path=='/issues/1/comments':return {'html_url':'summary'}
            raise AssertionError(path)
        with patch.object(client,'request',side_effect=request):result=client.publish(1,r,AFTER)
        self.assertIsNone(result['fix_pr']);self.assertFalse(any('/git/' in p for p in calls))

    def test_closed_pr_during_publish_refused(self):
        r,_=analyze_files(BEFORE,AFTER,base='b'*40,head='a'*40)
        client=GitHub('owner/repo','token');calls=[];reads=0
        def request(method,path,body=None):
            nonlocal reads
            calls.append((method,path))
            if path=='/pulls/3':
                reads+=1
                return {'state':'open' if reads==1 else 'closed','head':{'repo':{'full_name':'owner/repo'},'sha':r.head,'ref':'feature'},'base':{'repo':{'full_name':'owner/repo'},'sha':r.base}}
            if path=='/git/commits/'+r.head:return {'tree':{'sha':'parent'}}
            if path=='/git/trees':return {'sha':'tree'}
            if path.startswith('/git/matching-refs'):return []
            if path=='/git/commits':return {'sha':'commit'}
            raise AssertionError(path)
        with patch.object(client,'request',side_effect=request):
            with self.assertRaises(DocMendError):client.publish(3,r,AFTER)
        self.assertNotIn(('POST','/git/refs'),calls)

    def test_other_bot_summary_is_not_modified(self):
        client=GitHub('owner/repo','token');calls=[]
        def request(method,path,body=None):
            calls.append((method,path))
            if method=='GET':return [{'id':7,'body':'<!-- docmend-summary:v1 -->','user':{'type':'Bot','login':'other-app[bot]'}}]
            return {'html_url':'new'}
        with patch.object(client,'request',side_effect=request):self.assertEqual(client.comment(1,'new summary'),'new')
        self.assertEqual(calls[-1],('POST','/issues/1/comments'))

    def test_ref_creation_race_fails_without_force_or_pr(self):
        r,_=analyze_files(BEFORE,AFTER,base='b'*40,head='a'*40)
        client=GitHub('owner/repo','token');calls=[]
        def request(method,path,body=None):
            calls.append((method,path))
            if path=='/pulls/3':return {'state':'open','head':{'repo':{'full_name':'owner/repo'},'sha':r.head,'ref':'feature'},'base':{'repo':{'full_name':'owner/repo'},'sha':r.base}}
            if path=='/git/commits/'+r.head:return {'tree':{'sha':'parent'}}
            if path=='/git/trees':return {'sha':'tree'}
            if path.startswith('/git/matching-refs'):return []
            if path=='/git/commits':return {'sha':'commit'}
            if path=='/git/refs':raise DocMendError('GitHub HTTP 422; concurrent writer won')
            raise AssertionError(path)
        with patch.object(client,'request',side_effect=request):
            with self.assertRaises(DocMendError):client.publish(3,r,AFTER)
        self.assertFalse(any(method=='PATCH' or path=='/pulls' for method,path in calls))

    def test_two_concurrent_publishers_expose_one_branch(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        r,_=analyze_files(BEFORE,AFTER,base='b'*40,head='a'*40)
        barrier=threading.Barrier(2);lock=threading.Lock();state={'ref':False,'prs':0,'comments':0}
        pull={'state':'open','head':{'repo':{'full_name':'owner/repo'},'sha':r.head,'ref':'feature'},'base':{'repo':{'full_name':'owner/repo'},'sha':r.base}}
        def request(method,path,body=None):
            if path=='/pulls/3':return pull
            if path=='/git/commits/'+r.head:return {'tree':{'sha':'parent'}}
            if path=='/git/trees':return {'sha':'tree'}
            if path.startswith('/git/matching-refs'):return []
            if path=='/git/commits':return {'sha':'commit'}
            if path=='/git/refs':
                barrier.wait(timeout=5)
                with lock:
                    if state['ref']:raise DocMendError('Concurrent ref creation refused')
                    state['ref']=True
                return {}
            if path.startswith('/pulls?'):return []
            if path=='/pulls':
                with lock:state['prs']+=1
                return {'html_url':'repair'}
            if path.startswith('/issues/3/comments?'):return []
            if path=='/issues/3/comments':
                with lock:state['comments']+=1
                return {'html_url':'summary'}
            raise AssertionError(path)
        def publish():
            client=GitHub('owner/repo','token')
            with patch.object(client,'request',side_effect=request):
                try:return client.publish(3,r,AFTER)
                except DocMendError:return 'refused'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:publish(),range(2)))
        self.assertEqual(results.count('refused'),1)
        self.assertEqual(state,{'ref':True,'prs':1,'comments':1})
