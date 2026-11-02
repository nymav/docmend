import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
const port = Number(process.env.PORT || 8792);
createServer(async (req, res) => {
  try {
    const src = await readFile(new URL('../worker/index.js', import.meta.url), 'utf8');
    const worker = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));
    const response = await worker.default.fetch(new Request('http://127.0.0.1:' + port + req.url, { method: req.method }));
    res.writeHead(response.status, Object.fromEntries(response.headers));
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch { res.writeHead(500); res.end('Preview error'); }
}).listen(port, '127.0.0.1', () => console.log('Local: http://127.0.0.1:' + port));
