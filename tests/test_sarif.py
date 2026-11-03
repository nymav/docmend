import unittest
from docmend.models import Report, Finding
from docmend.sarif import sarif

class SarifTests(unittest.TestCase):
    def report(self,path='docs/a b.md'):
        r=Report('a','b','hash',[])
        r.findings=[Finding('section',path,'Heading','stale','Changed default',[]),Finding('other',path,'Other','review','Ambiguous',[]),Finding('ok',path,'OK','accurate','Matches',[])]
        r.warnings=['Unmapped symbol']
        return r
    def test_status_uri_and_limits(self):
        run=sarif(self.report())['runs'][0]
        self.assertEqual([x['level'] for x in run['results']],['error','warning'])
        self.assertEqual(run['results'][0]['locations'][0]['physicalLocation']['artifactLocation']['uri'],'docs/a%20b.md')
        self.assertEqual(len(run['invocations'][0]['toolExecutionNotifications']),1)
        self.assertEqual(sarif(self.report()),sarif(self.report()))
    def test_unsafe_paths(self):
        for path in ('../secret','/etc/passwd','docs\\secret'):
            with self.assertRaises(ValueError):sarif(self.report(path))
    def test_source_regions_use_actual_section_spans(self):
        report=self.report()
        result=sarif(report,[{'id':'section','path':'docs/a b.md','start':3,'end':7}])['runs'][0]['results'][0]
        self.assertEqual(result['locations'][0]['physicalLocation']['region'],{'startLine':4,'endLine':7})
