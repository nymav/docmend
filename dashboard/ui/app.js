import { validateReport, counts, filterFindings, lineDiff, makePatch, MAX_BYTES } from '/report-model.js';
const $ = s => document.querySelector(s);
const state = { reports: [], active: 0, selected: null, tab: 'patch', query: '', status: 'all' };
const labels = { stale: 'Outdated', review: 'Needs review', accurate: 'Matches code' };
const el = (tag, cls, value) => { const n = document.createElement(tag); if (cls) n.className = cls; if (value !== undefined) n.textContent = value; return n; };
const current = () => state.reports[state.active];
function message(text) { $('#message').textContent = text; $('#message').hidden = !text; }
function download(name, content, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = el('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function badge(status) { const n = el('span', 'badge ' + status); n.append(el('span', 'status-dot'), document.createTextNode(labels[status])); return n; }
function setReport(index) {
  state.active = index; state.selected = null; state.status = 'all'; state.query = ''; state.tab = 'patch';
  $('#search').value = ''; $('#status-filter').value = 'all'; message(''); render();
}
function renderLibrary() {
  $('#run-list').replaceChildren(); $('#library-count').textContent = state.reports.length;
  state.reports.forEach((entry, i) => {
    const b = el('button', 'run-item' + (state.active === i ? ' active' : ''), entry.name);
    b.type = 'button'; b.setAttribute('aria-pressed', String(state.active === i));
    const c = counts(entry.report);
    b.append(el('small', '', `${entry.sample ? 'DEMO' : 'IMPORTED'} · ${c.stale} outdated · ${c.review} review`));
    b.addEventListener('click', () => setReport(i)); $('#run-list').append(b);
  });
}
function render() {
  if (!current()) return;
  const entry = current(), r = entry.report, c = counts(r); renderLibrary();
  $('#report-name').textContent = entry.name;
  $('#report-origin').textContent = entry.sample ? 'Constructed end-to-end demo · saved engine output' : 'Imported report · browser memory only';
  $('#base-sha').textContent = r.base.slice(0, 8); $('#base-sha').title = r.base;
  $('#head-sha').textContent = r.head.slice(0, 8); $('#head-sha').title = r.head;
  $('#metrics').replaceChildren();
  const metrics = [['stale', c.stale, 'Outdated', 'Confirmed declaration drift'], ['review', c.review, 'Needs review', 'A person needs to check'], ['accurate', c.accurate, 'Matches code', 'Checked explicit declarations'], ['safe', c.safe, 'Proposed repairs', 'Marked safe by the engine']];
  for (const [kind, value, title, hint] of metrics) {
    const n = el('div', 'metric ' + kind), top = el('div', 'metric-top'); top.append(el('span', 'status-dot'), document.createTextNode(title));
    n.append(top, el('div', 'metric-value', value.toString().padStart(2, '0')), el('small', '', hint)); $('#metrics').append(n);
  }
  const visible = filterFindings(r, state.query, state.status);
  $('#visible-count').textContent = `${visible.length} / ${r.findings.length}`;
  if (state.selected === null || !visible.includes(r.findings[state.selected])) state.selected = visible.length ? r.findings.indexOf(visible[0]) : null;
  $('#findings-list').replaceChildren();
  for (const finding of visible) {
    const i = r.findings.indexOf(finding), b = el('button', 'finding' + (i === state.selected ? ' active' : ''));
    b.type = 'button'; b.setAttribute('aria-pressed', String(i === state.selected));
    const parts = finding.path.split('/'), file = parts.pop();
    b.append(el('div', 'finding-path', (parts.length ? parts.join('/') + '/' : '') + file), el('div', 'finding-title', finding.heading || 'Untitled section'));
    const bottom = el('div', 'finding-bottom'); bottom.append(badge(finding.status), el('small', '', finding.evidence === 'static' ? 'STATIC EVIDENCE' : 'REPORTED EVIDENCE')); b.append(bottom);
    b.addEventListener('click', () => { state.selected = i; state.tab = 'patch'; render(); }); $('#findings-list').append(b);
  }
  if (!visible.length) {
    const empty = el('div', 'empty'); empty.append(el('h3', '', r.findings.length ? 'No matching findings' : 'No findings in this report'), el('p', '', r.findings.length ? 'Try another search or status filter.' : `${r.changes.length} code changes recorded. No documentation findings were reported.`)); $('#findings-list').append(empty);
  }
  renderDetail();
}
function codeWindow(rows, offset = 0) {
  const box = el('div', 'code-window');
  for (const row of rows) { const line = el('div', 'code-line ' + row.kind); line.append(el('span', 'line-number', String(row.line + offset)), el('span', 'line-sign', row.kind === 'add' ? '+' : row.kind === 'remove' ? '−' : ' '), el('code', '', row.text)); box.append(line); }
  return box;
}
function renderDetail() {
  const d = $('#detail'); d.replaceChildren();
  const r = current().report, f = state.selected === null ? null : r.findings[state.selected];
  if (!f) { const n = el('div', 'empty'); n.append(el('div', 'empty-symbol', '✓'), el('h3', '', r.findings.length ? 'Nothing selected' : 'No reported drift'), el('p', '', r.findings.length ? 'Select a different filter to inspect a finding.' : 'This does not certify the entire documentation. Findings depend on changed code, supported declarations and mapping coverage.')); d.append(n); return; }
  const head = el('div', 'detail-heading'), title = el('div'); title.append(el('h3', '', f.heading || 'Untitled section'), el('div', 'detail-path', f.path)); head.append(title, badge(f.status)); d.append(head, el('p', 'diagnosis', f.reason));
  const edits = r.edits.filter(e => e.section_id === f.section_id && e.path === f.path);
  const tabs = el('div', 'detail-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Finding details');
  for (const [key, name] of [['patch', 'Proposed change'], ['evidence', 'Code evidence']]) {
    const b = el('button', '', name); b.type = 'button'; b.id = `tab-${key}`; b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', String(state.tab === key)); b.setAttribute('aria-controls', 'detail-panel'); b.tabIndex = state.tab === key ? 0 : -1;
    b.addEventListener('click', () => { state.tab = key; renderDetail(); $(`#tab-${key}`).focus(); });
    b.addEventListener('keydown', ev => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(ev.key)) { ev.preventDefault(); state.tab = key === 'patch' ? 'evidence' : 'patch'; if (ev.key === 'Home') state.tab = 'patch'; if (ev.key === 'End') state.tab = 'evidence'; renderDetail(); $(`#tab-${state.tab}`).focus(); } }); tabs.append(b);
  }
  d.append(tabs); const panel = el('div'); panel.id = 'detail-panel'; panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', 'tab-' + state.tab); d.append(panel);
  if (state.tab === 'patch') {
    if (!edits.length) { const n = el('div', 'empty'); n.append(el('div', 'empty-symbol', f.status === 'accurate' ? '✓' : '—'), el('h3', '', f.status === 'accurate' ? 'No correction proposed' : 'Human review required'), el('p', '', f.status === 'accurate' ? 'The checked declaration matches the code. Surrounding prose is not semantically certified.' : 'The engine did not produce a mechanically checkable repair for this finding. Follow the code evidence and review the section manually.')); panel.append(n); }
    for (const e of edits) {
      const cap = el('div', 'diff-title'); cap.append(el('span', '', 'DOCUMENTATION PATCH'), el('span', '', e.mode === 'safe' ? 'SAFE PROPOSAL' : 'DRAFT · REVIEW REQUIRED')); panel.append(cap, codeWindow(lineDiff(e.before, e.after), e.start));
      panel.append(el('p', 'patch-note', e.mode === 'safe' ? 'A precise declaration update. The CLI rechecks source evidence and file hashes before applying it.' : 'This draft requires explicit human review. It is excluded from patch export.'));
    }
  } else {
    const changes = r.changes.filter(c => f.unit_ids.includes(c.unit));
    if (!changes.length) panel.append(el('p', 'patch-note', 'No matching source snapshot is included for these symbol references. Inspect the repository using the report’s commit IDs.'));
    for (const c of changes) { const n = el('div', 'evidence-unit'); n.append(el('h4', '', c.unit)); for (const [key, label] of [['before', 'BASE COMMIT'], ['after', 'HEAD COMMIT']]) { n.append(el('div', 'evidence-' + key, label), el('pre', 'code-source', c[key]?.source || '(not present in this version)')); } panel.append(n); }
  }
  const actions = el('div', 'detail-actions'), safeEdits = edits.filter(e => e.mode === 'safe');
  if (safeEdits.length) { const b = el('button', 'secondary', 'Download proposed patch'); b.type = 'button'; b.addEventListener('click', () => { try { download('docmend-proposed.patch', makePatch(safeEdits), 'text/x-diff'); message('Patch downloaded. Review it against the original repository before applying. No files were changed here.'); } catch (e) { message(e.message); } }); actions.append(b); }
  else actions.append(el('small', '', 'No automatic repair to download.'));
  actions.append(el('small', '', 'Repository stays unchanged.')); d.append(actions);
  if (r.warnings?.length) { const warnings = el('div', 'patch-note'); warnings.append(el('strong', '', 'Engine note: '), document.createTextNode(r.warnings.join(' · '))); d.append(warnings); }
}
async function importFiles(files) {
  if (files.length > 20 || state.reports.length + files.length > 30) { message('Import at most 20 files at once and 30 reports per session.'); return; }
  let added = 0; const errors = [];
  for (const file of files) {
    try {
      if (file.size > MAX_BYTES) throw new Error('File exceeds the 10 MB limit.');
      const report = validateReport(JSON.parse(await file.text()));
      state.reports.push({ name: file.name, report, sample: false }); added++;
    } catch (e) { errors.push(`${file.name}: ${e instanceof SyntaxError ? 'Invalid JSON file.' : e.message}`); }
  }
  if (added) setReport(state.reports.length - 1);
  message([added ? `${added} report${added === 1 ? '' : 's'} imported locally. Files are not uploaded; this library resets on reload.` : '', ...errors].filter(Boolean).join(' '));
  $('#file-input').value = '';
}
for (const id of ['import-button', 'rail-import']) $('#' + id).addEventListener('click', () => $('#file-input').click());
$('#file-input').addEventListener('change', e => importFiles([...e.target.files]));
$('#search').addEventListener('input', e => { state.query = e.target.value; render(); });
$('#status-filter').addEventListener('change', e => { state.status = e.target.value; render(); });
$('#raw-export').addEventListener('click', () => { if (current()) download('docmend-report.json', JSON.stringify(current().report, null, 2), 'application/json'); });
for (const id of ['open-guide', 'scope-guide']) $('#' + id).addEventListener('click', () => $('#guide').showModal());
$('#close-guide').addEventListener('click', () => $('#guide').close());
$('#guide').addEventListener('click', e => { if (e.target === $('#guide')) { const r = $('#guide').getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) $('#guide').close(); } });
try {
  const responses = await Promise.all(['/demo-before.json', '/demo-after.json'].map(url => fetch(url)));
  if (responses.some(r => !r.ok)) throw new Error('Demo reports could not be loaded.');
  const reports = await Promise.all(responses.map(r => r.json()));
  state.reports = reports.map((r, i) => ({ name: i ? 'After repair' : 'Before repair', sample: true, report: validateReport(r) })); render();
} catch (e) { message(e.message + ' You can still import your own report.json.'); }
