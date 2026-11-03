"""SARIF 2.1.0 export. Review findings are warnings, never confirmed defects."""
from urllib.parse import quote
from pathlib import PurePosixPath
from .models import Report, digest


def sarif(report: Report, sections: list[dict] | None = None) -> dict:
    spans = {s["id"]: s for s in (sections or [])}
    results = []
    for finding in report.findings:
        if finding.status not in ('stale', 'review'):
            continue
        path = PurePosixPath(finding.path)
        if path.is_absolute() or '..' in path.parts or '\\' in finding.path:
            raise ValueError('SARIF paths must be repository-relative')
        physical = {'artifactLocation': {'uri': quote(finding.path, safe='/'), 'uriBaseId': '%SRCROOT%'}}
        span = spans.get(finding.section_id)
        if span and span['path'] == finding.path and type(span['start']) is int and type(span['end']) is int and 0 <= span['start'] < span['end']:
            physical['region'] = {'startLine': span['start'] + 1, 'endLine': span['end']}
        results.append({
            'ruleId': 'docmend/' + finding.status,
            'level': 'error' if finding.status == 'stale' else 'warning',
            'message': {'text': finding.heading + ': ' + finding.reason},
            'locations': [{'physicalLocation': physical}],
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
