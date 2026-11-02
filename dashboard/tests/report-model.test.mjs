import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { validateReport, counts, filterFindings, lineDiff, makePatch } from '../ui/report-model.js';
const original = JSON.parse(readFileSync(new URL('../ui/demo-before.json', import.meta.url)));
const copy = () => structuredClone(original);
test('real engine report has one stale declaration and one safe proposal', () => {
  assert.deepEqual(counts(validateReport(copy())), { stale: 1, review: 0, accurate: 0, safe: 1, draft: 0 });
});
test('actual recheck has an accurate declaration and no proposed repair', () => {
  const r = validateReport(JSON.parse(readFileSync(new URL('../ui/demo-after.json', import.meta.url))));
  assert.deepEqual(counts(r), { stale: 0, review: 0, accurate: 1, safe: 0, draft: 0 });
});
test('filter matches symbol names without changing the report', () => {
  assert.equal(filterFindings(original, 'FETCH', 'stale').length, 1);
  assert.equal(filterFindings(original, 'fetch', 'review').length, 0);
  assert.equal(filterFindings(original, 'unrelated').length, 0);
});
test('incompatible report versions and malformed commits are rejected', () => {
  for (const mutate of [r => r.schema_version = 9, r => r.head = '--help', r => r.findings = {}, r => r.findings[0].status = 'certified']) {
    const r = copy(); mutate(r); assert.throws(() => validateReport(r));
  }
});
test('unsafe patch paths, mismatched ranges and missing hashes are rejected', () => {
  for (const mutate of [r => r.edits[0].path = '../../etc/passwd', r => r.edits[0].path = 'docs/test\n+++ x', r => r.edits[0].end = 500, r => r.edits[0].file_hash = 'not-a-hash']) {
    const r = copy(); mutate(r); assert.throws(() => validateReport(r));
  }
});
test('diff preserves common heading and isolates the signature change', () => {
  const rows = lineDiff(original.edits[0].before, original.edits[0].after);
  assert.equal(rows.filter(r => r.kind === 'remove').length, 1);
  assert.equal(rows.filter(r => r.kind === 'add').length, 1);
  assert.equal(rows[0].kind, 'context');
});
test('downloaded patch really applies with git apply and produces expected text', () => {
  const root = mkdtempSync(join(tmpdir(), 'docmend-viewer-'));
  try {
    execFileSync('git', ['init', '-q', root]); mkdirSync(join(root, 'docs'));
    const e = original.edits[0]; writeFileSync(join(root, e.path), e.before);
    execFileSync('git', ['apply', '--check', '-'], { cwd: root, input: makePatch([e]) });
    execFileSync('git', ['apply', '-'], { cwd: root, input: makePatch([e]) });
    assert.equal(readFileSync(join(root, e.path), 'utf8'), e.after);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
test('drafts, overlapping edits and inconsistent source hashes cannot become safe exports', () => {
  const e = original.edits[0];
  assert.throws(() => makePatch([{ ...e, mode: 'draft' }]));
  assert.throws(() => makePatch([e, e]));
  assert.throws(() => makePatch([e, { ...e, start: 4, end: 7, file_hash: 'a'.repeat(64) }]));
});
test('patch handles two sections, line offsets and no final newline', () => {
  const root = mkdtempSync(join(tmpdir(), 'docmend-offset-'));
  try {
    execFileSync('git', ['init', '-q', root]);
    writeFileSync(join(root, 'readme.md'), 'first\nkeep\nlast');
    const hash = 'a'.repeat(64);
    const edits = [
      { mode: 'safe', path: 'readme.md', start: 0, end: 1, before: 'first\n', after: 'first\nextra\n', file_hash: hash },
      { mode: 'safe', path: 'readme.md', start: 2, end: 3, before: 'last', after: 'changed', file_hash: hash }
    ];
    execFileSync('git', ['apply', '--unidiff-zero', '-'], { cwd: root, input: makePatch(edits) });
    assert.equal(readFileSync(join(root, 'readme.md'), 'utf8'), 'first\nextra\nkeep\nchanged');
  } finally { rmSync(root, { recursive: true, force: true }); }
});
