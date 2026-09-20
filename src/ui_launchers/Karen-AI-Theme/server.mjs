import http from 'node:http';
import next from 'next';

const hostname = process.env.WEB_HOST || '0.0.0.0';
const port = Number.parseInt(process.env.PORT || '8010', 10);

if (!Number.isInteger(port) || port <= 0 || port > 65535) {
  throw new Error(`Invalid PORT: ${process.env.PORT ?? ''}`);
}

function normalizeRemoteAddress(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  if (raw.startsWith('::ffff:')) return raw.slice(7);
  const zoneIndex = raw.indexOf('%');
  return zoneIndex >= 0 ? raw.slice(0, zoneIndex) : raw;
}

const app = next({ dev: false, hostname, port });
const handle = app.getRequestHandler();

await app.prepare();

const server = http.createServer((req, res) => {
  const clientIp = normalizeRemoteAddress(req.socket.remoteAddress);

  // This process is the canonical public HTTP ingress for the production web
  // container. Always overwrite forwarding identity from the actual socket so
  // browser-supplied X-Forwarded-For/X-Real-IP values cannot become authority.
  if (clientIp) {
    req.headers['x-forwarded-for'] = clientIp;
    req.headers['x-real-ip'] = clientIp;
  } else {
    delete req.headers['x-forwarded-for'];
    delete req.headers['x-real-ip'];
  }

  handle(req, res).catch((error) => {
    console.error('[web-ingress] request handling failed', error);
    if (!res.headersSent) {
      res.statusCode = 500;
      res.end('Internal Server Error');
    } else {
      res.destroy(error instanceof Error ? error : undefined);
    }
  });
});

server.on('clientError', (_error, socket) => {
  socket.end('HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n');
});

server.listen(port, hostname, () => {
  console.log(`[web-ingress] listening on http://${hostname}:${port}`);
});

function shutdown(signal) {
  console.log(`[web-ingress] received ${signal}; closing`);
  server.close((error) => {
    if (error) {
      console.error('[web-ingress] graceful shutdown failed', error);
      process.exitCode = 1;
    }
  });
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
