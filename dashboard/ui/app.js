import { validateReport, counts, filterFindings, lineDiff, makePatch, MAX_BYTES } from '/report-model.js';
const $ = s => document.querySelector(s);
const state = { reports: [], active: 0, selected: null, query: '', status: 'all' };
const labels = { stale: 'Outdated', review: 'Needs review', accurate: 'Matches code' };
const el = (tag, cls, value) => { const n = document.createElement(tag); if (cls) n.className = cls; if (value !== undefined) n.textContent = value; return n; };
const current = () => state.reports[state.active];
function message(text) {
  for (const id of ['message', 'welcome-message']) { $('#' + id).textContent = text; $('#' + id).hidden = !text; }
}
function download(name, content, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = el('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function badge(status) { const n = el('span', 'badge ' + status); n.append(el('span', 'status-dot'), document.createTextNode(labels[status])); return n; }
function showWelcome() { document.body.classList.add('welcome-mode'); $('#welcome').hidden = false; $('#review-workspace').hidden = true; $('#welcome-title').focus(); }
function showReview() {
  document.body.classList.remove('welcome-mode');
  $('#welcome').hidden = true; $('#review-workspace').hidden = false; $('#workspace-button').hidden = false;
}
function setReport(index) {
  if (!state.reports[index]) return;
  state.active = index; state.selected = null; state.status = 'all'; state.query = '';
  $('#search').value = ''; $('#status-filter').value = 'all'; message(''); showReview(); render();
}
function renderLibrary() {
  $('#run-list').replaceChildren(); $('#library-count').textContent = state.reports.length;
  state.reports.forEach((entry, i) => {
    const b = el('button', 'run-item' + (state.active === i ? ' active' : ''), entry.name);
    b.type = 'button'; b.setAttribute('aria-pressed', String(state.active === i));
    const c = counts(entry.report);
    b.append(el('small', '', `${entry.sample ? 'EXAMPLE' : 'YOUR FILE'} · ${c.stale} outdated · ${c.review} review`));
    b.addEventListener('click', () => setReport(i)); $('#run-list').append(b);
  });
}
function render() {
  if (!current()) return;
  const entry = current(), r = entry.report, c = counts(r); renderLibrary();
  $('#report-name').textContent = entry.name;
  $('#report-origin').textContent = entry.sample ? 'Included example · actual saved engine output' : 'Your report · opened locally';
  const context = $('#example-context'); context.replaceChildren(); context.hidden = !entry.sample;
  if (entry.sample) {
    const after = entry.stage === 'after';
    context.append(el('span', 'example-label', 'EXAMPLE'), el('p', '', after ? 'The documentation was corrected, then checked again. The declaration now matches the code.' : 'The code’s timeout changed from 30 to 60. The documentation still says 30. Compare both below, then download the proposed correction.'));
    const next = state.reports.findIndex(x => x.sample && x.stage === (after ? 'before' : 'after'));
    if (next >= 0) { const b = el('button', 'text-button', after ? 'View original issue' : 'View rechecked result'); b.addEventListener('click', () => setReport(next)); context.append(b); }
  }
  $('#base-sha').textContent = r.base.slice(0, 8); $('#base-sha').title = r.base;
  $('#head-sha').textContent = r.head.slice(0, 8); $('#head-sha').title = r.head;
  $('#metrics').replaceChildren();
  for (const [kind, value, title] of [['stale', c.stale, 'Outdated'], ['review', c.review, 'Needs review'], ['accurate', c.accurate, 'Matches code'], ['safe', c.safe, 'Proposed repairs']]) {
    const n = el('div', 'metric ' + kind), top = el('div', 'metric-top'); top.append(el('span', 'status-dot'), document.createTextNode(title));
    n.append(top, el('div', 'metric-value', String(value))); $('#metrics').append(n);
  }
  const visible = filterFindings(r, state.query, state.status);
  $('#visible-count').textContent = `${visible.length} / ${r.findings.length}`;
  if (state.selected === null || !visible.includes(r.findings[state.selected])) state.selected = visible.length ? r.findings.indexOf(visible[0]) : null;
  $('#findings-list').replaceChildren();
  for (const f of visible) {
    const i = r.findings.indexOf(f), b = el('button', 'finding' + (i === state.selected ? ' active' : ''));
    b.type = 'button'; b.setAttribute('aria-pressed', String(i === state.selected));
    b.append(el('div', 'finding-path', f.path), el('div', 'finding-title', f.heading || 'Untitled section'));
    const bottom = el('div', 'finding-bottom'); bottom.append(badge(f.status), el('small', '', f.evidence === 'static' ? 'Code-backed' : 'Reported evidence')); b.append(bottom);
    b.addEventListener('click', () => { state.selected = i; render(); }); $('#findings-list').append(b);
  }
  if (!visible.length) {
    const empty = el('div', 'empty'); empty.append(el('h3', '', r.findings.length ? 'No matching findings' : 'No findings in this report'), el('p', '', r.findings.length ? 'Try another search or status filter.' : `${r.changes.length} code changes recorded. No documentation findings were reported.`)); $('#findings-list').append(empty);
  }
  renderDetail(visible);
}
function codeWindow(rows, offset = 0) {
  const box = el('div', 'code-window');
  for (const row of rows) {
    const line = el('div', 'code-line ' + row.kind);
    line.append(el('span', 'line-number', String(row.line + offset)), el('span', 'line-sign', row.kind === 'add' ? '+' : row.kind === 'remove' ? '−' : ' '), el('code', '', row.text)); box.append(line);
  }
  return box;
}
function sectionTitle(number, title, hint) {
  const header = el('div', 'review-section-heading'), left = el('div');
  left.append(el('span', 'section-number', number), el('h4', '', title)); header.append(left);
  if (hint) header.append(el('span', 'section-hint', hint)); return header;
}
function renderDetail(visible) {
  const d = $('#detail'); d.replaceChildren();
  const r = current().report, f = state.selected === null ? null : r.findings[state.selected];
  if (!f) {
    const n = el('div', 'empty'); n.append(el('div', 'empty-symbol', r.findings.length ? '—' : '✓'), el('h3', '', r.findings.length ? 'No matching findings' : 'No reported drift'), el('p', '', r.findings.length ? 'Clear your search or change the status filter to see the report’s findings.' : 'This report contains no documentation findings. Detection depends on changed code, supported declarations and mapping coverage.')); d.append(n); return;
  }
  const heading = el('div', 'detail-heading'), title = el('div');
  title.append(el('h3', '', f.heading || 'Untitled section'), el('div', 'detail-path', f.path)); heading.append(title, badge(f.status)); d.append(heading);
  const summary = el('div', 'diagnosis'); summary.append(el('strong', '', f.status === 'stale' ? 'Why this needs attention' : f.status === 'accurate' ? 'What was checked' : 'What to review'), el('p', '', f.reason)); d.append(summary);
  const changes = r.changes.filter(c => f.unit_ids.includes(c.unit));
  const evidence = el('section', 'evidence-section'); evidence.setAttribute('aria-label', 'Code evidence');
  evidence.append(sectionTitle('1', 'Code evidence', 'Compared commits'));
  if (!changes.length) evidence.append(el('p', 'patch-note', 'This report does not include a matching source snapshot. Use its commit IDs and symbol references to inspect the original repository.'));
  for (const c of changes) {
    const unit = el('div', 'evidence-unit'); unit.append(el('div', 'unit-label', c.unit));
    const pair = el('div', 'source-pair');
    for (const [key, label] of [['before', 'Before the change'], ['after', 'After the change']]) {
      const side = el('div', 'source-side ' + key); side.append(el('div', 'source-label', label), el('pre', 'code-source', c[key]?.source || '(not present in this version)')); pair.append(side);
    }
    unit.append(pair); evidence.append(unit);
  }
  d.append(evidence);
  const edits = r.edits.filter(e => e.section_id === f.section_id && e.path === f.path);
  const correction = el('section', 'correction-section'); correction.setAttribute('aria-label', 'Documentation correction');
  correction.append(sectionTitle('2', 'Documentation correction', edits.length ? 'Exact proposed text' : 'No patch proposed'));
  if (!edits.length) {
    const n = el('div', 'outcome ' + f.status); n.append(el('h4', '', f.status === 'accurate' ? 'The checked declaration matches.' : 'A person needs to review this.'), el('p', '', f.status === 'accurate' ? 'No correction is proposed. This check covers the explicit declaration, not every sentence around it.' : 'There is no mechanically checkable repair for this finding. Review the documentation using the code evidence above.')); correction.append(n);
  }
  for (const e of edits) {
    const cap = el('div', 'diff-title'); cap.append(el('span', '', 'DOCUMENTATION'), el('span', '', e.mode === 'safe' ? 'Engine-marked safe proposal' : 'Draft · human review required'));
    correction.append(cap, codeWindow(lineDiff(e.before, e.after), e.start));
    if (e.mode === 'draft') correction.append(el('p', 'patch-note', 'This draft needs explicit review and is excluded from patch downloads.'));
  }
  d.append(correction);
  const safe = edits.filter(e => e.mode === 'safe');
  if (safe.length) {
    const action = el('section', 'next-action'); action.setAttribute('aria-label', 'Download correction');
    const copy = el('div'); copy.append(el('strong', '', 'Ready to take this to your repository?'), el('p', '', 'Download the proposed patch. Review it before applying.'));
    const b = el('button', 'primary', 'Download patch'); b.type = 'button';
    b.addEventListener('click', () => {
      try { download('docmend-proposed.patch', makePatch(safe), 'text/x-diff'); message('Patch downloaded. No repository files were changed. Apply it in your checkout after review, or use DocMend’s guarded apply command with the original report.'); }
      catch (error) { message(error.message); }
    }); action.append(copy, b); d.append(action);
    const instructions = el('details', 'apply-help'); instructions.append(el('summary', '', 'How do I apply the correction?'));
    const body = el('div'); body.append(el('p', '', 'For source and file-hash checks, use the original report with the DocMend CLI:'), el('pre', 'code-source', 'docmend apply --repo /path/to/repository \\\n  --report /path/to/report.json'), el('p', '', 'Or inspect the downloaded patch with git apply --check --unidiff-zero before applying it. The viewer itself never changes files.')); instructions.append(body); d.append(instructions);
  }
  const position = visible.indexOf(f), navigation = el('nav', 'finding-navigation'); navigation.setAttribute('aria-label', 'Move between findings');
  navigation.append(el('span', '', `Finding ${position + 1} of ${visible.length}`));
  if (visible.length > 1) {
    for (const [delta, label] of [[-1, 'Previous'], [1, 'Next finding']]) {
      const b = el('button', 'secondary', label); b.disabled = position + delta < 0 || position + delta >= visible.length;
      b.addEventListener('click', () => selectRelative(delta)); navigation.append(b);
    }
  }
  d.append(navigation);
  if (r.warnings?.length) { const note = el('details', 'engine-notes'); note.append(el('summary', '', 'Check limitations (' + r.warnings.length + ')'), el('p', '', r.warnings.join(' · '))); d.append(note); }
}
function selectRelative(delta) {
  const r = current()?.report; if (!r) return;
  const visible = filterFindings(r, state.query, state.status), position = visible.indexOf(r.findings[state.selected]);
  const next = visible[position + delta]; if (next) { state.selected = r.findings.indexOf(next); render(); }
}
async function importFiles(files) {
  if (files.length > 20 || state.reports.length + files.length > 30) { message('Import at most 20 files at once and 30 reports per session.'); return; }
  let added = 0; const errors = [];
  for (const file of files) {
    try {
      if (file.size > MAX_BYTES) throw new Error('File exceeds the 10 MB limit.');
      const report = validateReport(JSON.parse(await file.text()));
      state.reports.push({ name: file.name, report, sample: false }); added++;
    } catch (error) { errors.push(`${file.name}: ${error instanceof SyntaxError ? 'Invalid JSON file.' : error.message}`); }
  }
  if (added) { setReport(state.reports.length - 1); $('#report-name').focus(); }
  message([added ? `${added} report${added === 1 ? '' : 's'} opened locally. Nothing was uploaded. Reloading clears this session.` : '', ...errors].filter(Boolean).join(' '));
  $('#file-input').value = '';
}
for (const id of ['import-button', 'rail-import', 'welcome-import']) $('#' + id).addEventListener('click', () => $('#file-input').click());
$('#file-input').addEventListener('change', e => importFiles([...e.target.files]));
$('#home-button').addEventListener('click', showWelcome);
$('#workspace-button').addEventListener('click', () => { if (current()) { showReview(); render(); } });
$('#try-example').addEventListener('click', () => {
  const index = state.reports.findIndex(r => r.sample && r.stage === 'before');
  if (index >= 0) { setReport(index); $('#report-name').focus(); }
  else message('The example is still loading or unavailable. You can open your own report at any time.');
});
$('#welcome-title').tabIndex = -1;
$('#search').addEventListener('input', e => { state.query = e.target.value; render(); });
$('#status-filter').addEventListener('change', e => { state.status = e.target.value; render(); });
$('#raw-export').addEventListener('click', () => { if (current()) download('docmend-report.json', JSON.stringify(current().report, null, 2), 'application/json'); });
for (const id of ['open-guide', 'scope-guide']) $('#' + id).addEventListener('click', () => $('#guide').showModal());
$('#close-guide').addEventListener('click', () => $('#guide').close());
$('#guide').addEventListener('click', e => { if (e.target === $('#guide')) { const r = $('#guide').getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) $('#guide').close(); } });
let dragDepth = 0;
document.addEventListener('dragover', e => { if (e.dataTransfer?.types.includes('Files')) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } });
document.addEventListener('dragenter', e => { if (e.dataTransfer?.types.includes('Files')) { e.preventDefault(); dragDepth++; document.body.classList.add('file-drag'); } });
document.addEventListener('dragleave', e => { if (e.dataTransfer?.types.includes('Files') && --dragDepth <= 0) { dragDepth = 0; document.body.classList.remove('file-drag'); } });
document.addEventListener('drop', e => { e.preventDefault(); dragDepth = 0; document.body.classList.remove('file-drag'); if (e.dataTransfer?.files.length) importFiles([...e.dataTransfer.files]); });
document.addEventListener('keydown', e => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
  if (!typing && !e.metaKey && !e.ctrlKey && !e.altKey && !$('#guide').open && !$('#review-workspace').hidden) {
    if (e.key === '/') { e.preventDefault(); $('#search').focus(); }
    if (e.key === 'j') selectRelative(1);
    if (e.key === 'k') selectRelative(-1);
  }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'o' && !$('#guide').open) { e.preventDefault(); $('#file-input').click(); }
  if (e.key === 'Escape' && document.activeElement === $('#search')) { state.query = ''; $('#search').value = ''; render(); }
});
try {
  const responses = await Promise.all(['/demo-before.json', '/demo-after.json'].map(url => fetch(url)));
  if (responses.some(r => !r.ok)) throw new Error('Example reports could not be loaded.');
  const reports = await Promise.all(responses.map(r => r.json()));
  state.reports.push(...reports.map((r, i) => ({ name: i ? 'After repair' : 'Before repair', stage: i ? 'after' : 'before', sample: true, report: validateReport(r) })));
  renderLibrary();
} catch (error) { message(error.message + ' You can still open your own report.json.'); }
