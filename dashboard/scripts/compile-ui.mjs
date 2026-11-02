import { readFile, writeFile } from 'node:fs/promises';
const assets = {};
for (const file of ['index.html', 'styles.css', 'app.js', 'report-model.js', 'demo-before.json', 'demo-after.json']) {
  const content = await readFile(new URL('../ui/' + file, import.meta.url), 'utf8');
  const type = file.endsWith('.html') ? 'text/html' : file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'application/json';
  assets[file === 'index.html' ? '/' : '/' + file] = { content, type };
}
const source = `// Generated from ui/ by scripts/compile-ui.mjs. No credentials or user reports are bundled.
const assets = ${JSON.stringify(assets)};
export default {
  async fetch(request) {
    const path = new URL(request.url).pathname;
    const headers = {
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
      'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
      'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'"
    };
    if (!['GET', 'HEAD'].includes(request.method)) return new Response('Method not allowed', { status: 405, headers: { ...headers, Allow: 'GET, HEAD' } });
    const asset = assets[path];
    if (!asset) return new Response('Not found', { status: 404, headers });
    return new Response(request.method === 'HEAD' ? null : asset.content, { headers: { ...headers, 'Content-Type': asset.type + '; charset=utf-8' } });
  }
};
`;
await writeFile(new URL('../worker/index.js', import.meta.url), source);
console.log('Compiled six local assets into the Worker module.');
