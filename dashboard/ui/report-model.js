/** Validate untrusted reports without interpreting Markdown or executing source. */
export const MAX_BYTES = 10 * 1024 * 1024;
const statuses = new Set(['stale', 'review', 'accurate']);
const text = (v, name, limit = 1000000) => {
  if (typeof v !== 'string' || v.length > limit || v.includes('\0')) throw new Error(`Invalid ${name}.`);
  return v;
};
const array = (v, name, limit = 3000) => {
  if (!Array.isArray(v) || v.length > limit) throw new Error(`Invalid ${name}.`);
  return v;
};
const path = v => {
  text(v, 'file path', 2000);
  if (!v || /[\r\n\t\\]/.test(v) || v.startsWith('/') || v.split('/').some(p => p === '..' || p === '.')) throw new Error('Unsafe file path in report.');
};
export function validateReport(raw) {
  if (!raw || raw.schema_version !== 1) throw new Error('Choose a DocMend schema version 1 report.json file.');
  for (const key of ['base', 'head']) {
    if (!/^[a-f0-9]{40,64}$/.test(raw[key])) throw new Error(`Invalid ${key} commit.`);
  }
  for (const f of array(raw.findings, 'findings')) {
    if (!f || !statuses.has(f.status)) throw new Error('Invalid finding status.');
    path(f.path); text(f.heading, 'section heading', 10000); text(f.reason, 'diagnosis');
    text(f.section_id, 'section ID', 10000); text(f.evidence, 'evidence', 10000);
    array(f.unit_ids, 'symbol references').forEach(v => text(v, 'symbol', 10000));
  }
  for (const e of array(raw.edits, 'edits')) {
    if (!e || !['safe', 'draft'].includes(e.mode)) throw new Error('Invalid edit mode.');
    path(e.path); text(e.section_id, 'section ID', 10000);
    text(e.before, 'original text'); text(e.after, 'replacement text');
    if (![e.start, e.end].every(Number.isSafeInteger) || e.start < 0 || e.end < e.start) throw new Error('Invalid edit range.');
    if ((e.before ? e.before.split('\n').length - (e.before.endsWith('\n') ? 1 : 0) : 0) !== e.end - e.start) throw new Error('Edit text does not match its line range.');
    if (!/^[a-f0-9]{64}$/.test(e.file_hash)) throw new Error('Invalid edit file hash.');
  }
  for (const c of array(raw.changes, 'code changes')) {
    if (!c) throw new Error('Invalid code change.');
    path(c.path); text(c.unit, 'symbol', 10000); text(c.kind, 'change kind', 1000);
    for (const key of ['before', 'after']) if (c[key]) {
      text(c[key].source, 'source code');
      if (c[key].facts?.signature !== undefined) text(c[key].facts.signature, 'signature');
    }
  }
  if (raw.warnings !== undefined) array(raw.warnings, 'warnings').forEach(v => text(v, 'warning'));
  return raw;
}
export function counts(report) {
  const result = { stale: 0, review: 0, accurate: 0, safe: 0, draft: 0 };
  for (const f of report.findings) result[f.status]++;
  for (const e of report.edits) result[e.mode]++;
  return result;
}
export function filterFindings(report, query = '', status = 'all') {
  const q = query.toLowerCase().trim();
  return report.findings.filter(f => (status === 'all' || f.status === status) &&
    [f.path, f.heading, f.reason, ...f.unit_ids].some(v => v.toLowerCase().includes(q)));
}
export function lineDiff(before, after) {
  const split = s => { const r = s.split('\n'); if (s.endsWith('\n')) r.pop(); return r; };
  const a = split(before), b = split(after);
  let start = 0, end = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  while (end < a.length - start && end < b.length - start && a[a.length - end - 1] === b[b.length - end - 1]) end++;
  return [...a.slice(0, start).map((s, i) => ({ kind: 'context', text: s, line: i + 1 })),
    ...a.slice(start, a.length - end).map((s, i) => ({ kind: 'remove', text: s, line: start + i + 1 })),
    ...b.slice(start, b.length - end).map((s, i) => ({ kind: 'add', text: s, line: start + i + 1 })),
    ...b.slice(b.length - end).map((s, i) => ({ kind: 'context', text: s, line: b.length - end + i + 1 }))];
}
/** This is a proposal, not revalidation. The engine rechecks hashes on apply. */
export function makePatch(edits) {
  if (!edits.length) return '';
  const files = new Map();
  for (const e of edits) {
    if (e.mode !== 'safe') throw new Error('Draft edits must be reviewed separately.');
    if (!files.has(e.path)) files.set(e.path, []);
    files.get(e.path).push(e);
  }
  let patch = '';
  const lines = s => s ? s.split('\n').slice(0, s.endsWith('\n') ? -1 : undefined) : [];
  for (const [file, entries] of files) {
    const quote = s => /[^a-zA-Z0-9_./-]/.test(s) ? JSON.stringify(s) : s;
    patch += `--- ${quote('a/' + file)}\n+++ ${quote('b/' + file)}\n`;
    let offset = 0, lastEnd = -1, hash = entries[0].file_hash;
    for (const e of entries.sort((a, b) => a.start - b.start)) {
      if (e.start < lastEnd || e.file_hash !== hash) throw new Error('Conflicting edits in this report. Export JSON for CLI review instead.');
      lastEnd = e.end;
      const a = lines(e.before), b = lines(e.after);
      const oldStart = a.length ? e.start + 1 : e.start;
      const newStart = b.length ? e.start + offset + 1 : e.start + offset;
      patch += `@@ -${oldStart},${a.length} +${newStart},${b.length} @@\n`;
      for (const [prefix, content, list] of [['-', e.before, a], ['+', e.after, b]]) {
        patch += list.map(s => prefix + s + '\n').join('');
        if (list.length && !content.endsWith('\n')) patch += '\\ No newline at end of file\n';
      }
      offset += b.length - a.length;
    }
  }
  return patch;
}
