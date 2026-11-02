import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../worker/index.js';
test('all essential assets are served without external CDN dependencies', async () => {
  for (const path of ['/', '/app.js', '/styles.css', '/report-model.js', '/demo-before.json', '/demo-after.json']) {
    const response = await worker.fetch(new Request('https://docmend.test' + path));
    assert.equal(response.status, 200); assert.ok(response.headers.get('content-type'));
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.ok(response.headers.get('content-security-policy').includes("script-src 'self'"));
  }
});
test('no upload or repository mutation endpoints exist', async () => {
  assert.equal((await worker.fetch(new Request('https://docmend.test/api/upload', { method: 'POST' }))).status, 405);
  assert.equal((await worker.fetch(new Request('https://docmend.test/api/token'))).status, 404);
});
test('head requests have no body and report fixtures are parseable', async () => {
  assert.equal(await (await worker.fetch(new Request('https://docmend.test/', { method: 'HEAD' }))).text(), '');
  const response = await worker.fetch(new Request('https://docmend.test/demo-before.json'));
  assert.equal((await response.json()).schema_version, 1);
});
