"""SARIF 2.1.0 export. Review findings are warnings, never confirmed defects."""
from urllib.parse import quote
from pathlib import PurePosixPath
from .models import Report, digest


def sarif(report: Report) -> dict:
    results = []
    for finding in report.findings:
        if finding.status not in ('stale', 'review'):
            continue
        path = PurePosixPath(finding.path)
        if path.is_absolute() or '..' in path.parts or '\\' in finding.path:
            raise ValueError('SARIF paths must be repository-relative')
        results.append({
            'ruleId': 'docmend/' + finding.status,
            'level': 'error' if finding.status == 'stale' else 'warning',
            'message': {'text': finding.heading + ': ' + finding.reason},
            'locations': [{'physicalLocation': {'artifactLocation': {
                'uri': quote(finding.path, safe='/'), 'uriBaseId': '%SRCROOT%'}}}],
            'partialFingerprints': {'docmendSection/v1': digest(finding.section_id + ':' + finding.status)},
            'properties': {'evidence': finding.evidence, 'requiresHumanReview': True},
        })
    return {'version': '2.1.0', '$schema': 'https://json.schemastore.org/sarif-2.1.0.json', 'runs': [{
        'tool': {'driver': {'name': 'DocMend', 'rules': [
            {'id': 'docmend/stale', 'shortDescription': {'text': 'Confirmed documentation drift'}},
            {'id': 'docmend/review', 'shortDescription': {'text': 'Documentation requires review'}},
        ]}}, 'results': results,
        'invocations': [{'executionSuccessful': True, 'toolExecutionNotifications': [
            {'level': 'warning', 'message': {'text': warning}} for warning in report.warnings]}],
    }]}
