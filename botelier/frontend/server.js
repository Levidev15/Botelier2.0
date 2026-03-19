const { createServer } = require('http');
const { parse } = require('url');
const net = require('net');
const next = require('next');
const { createProxyMiddleware } = require('http-proxy-middleware');

const dev = process.env.NODE_ENV !== 'production';
const hostname = '0.0.0.0';
const port = parseInt(process.env.PORT || '5000', 10);
const backendUrl = process.env.BACKEND_URL || 'http://localhost:3001';

// Ensure NEXTAUTH_URL is always set.
// In production, NEXTAUTH_URL may not be explicitly configured, so we derive it
// from REPLIT_DOMAINS (the canonical public domain Replit assigns to deployed apps).
if (!process.env.NEXTAUTH_URL) {
  const replitDomains = process.env.REPLIT_DOMAINS || process.env.REPLIT_DEV_DOMAIN;
  if (replitDomains) {
    const primaryDomain = replitDomains.split(',')[0].trim();
    process.env.NEXTAUTH_URL = `https://${primaryDomain}`;
    console.log(`🔑 NEXTAUTH_URL derived from Replit domain: ${process.env.NEXTAUTH_URL}`);
  }
}

const app = next({ dev, hostname, port });
const handle = app.getRequestHandler();

const apiProxy = createProxyMiddleware({
  target: backendUrl,
  changeOrigin: true,
  logLevel: 'silent',
  onProxyReq: (proxyReq, req, res) => {
    console.log(`🔄 Proxying ${req.method} ${req.url} to backend`);
  },
  onError: (err, req, res) => {
    console.error(`❌ Proxy error for ${req.url}:`, err.message);
    if (res && res.writeHead) {
      res.writeHead(500, { 'Content-Type': 'text/plain' });
      res.end('Proxy error');
    }
  }
});

// Parse backend host/port once at startup for the raw WS relay.
const backendParsed = new URL(backendUrl);
const backendHost = backendParsed.hostname;
const backendPort = parseInt(backendParsed.port || '80', 10);

/**
 * Raw TCP WebSocket relay for /api/ws/* (Twilio Media Streams).
 *
 * http-proxy-middleware relays WebSocket traffic through Node.js streams
 * which use Nagle's algorithm by default, batching the 160-byte μ-law
 * audio frames that Twilio sends every 20ms. That batching causes audible
 * choppiness in prod (where WS goes through this Node.js server) even
 * though dev is fine (where Twilio connects to FastAPI directly on :3001).
 *
 * Using net.Socket with setNoDelay(true) on both sides disables Nagle and
 * gives every audio frame its own TCP segment — the same zero-buffering
 * behaviour nginx uses for WebSocket proxying.
 */
function relayWebSocket(req, socket, head) {
  // Disable Nagle on the incoming Twilio socket immediately.
  socket.setNoDelay(true);

  const proxySocket = net.connect(backendPort, backendHost, () => {
    // Disable Nagle on the outgoing FastAPI socket.
    proxySocket.setNoDelay(true);

    // Re-emit the original HTTP upgrade request to the backend.
    let upgradeReq = `${req.method} ${req.url} HTTP/1.1\r\n`;
    for (const [key, value] of Object.entries(req.headers)) {
      upgradeReq += `${key}: ${value}\r\n`;
    }
    upgradeReq += '\r\n';
    proxySocket.write(upgradeReq);

    // Forward any buffered bytes that arrived after the HTTP headers
    // (typically empty for WebSocket upgrades, but safe to include).
    if (head && head.length > 0) {
      proxySocket.write(head);
    }

    // Bidirectional raw pipe — no parsing, no buffering.
    socket.pipe(proxySocket, { end: false });
    proxySocket.pipe(socket, { end: false });
  });

  // --- Symmetric cleanup: either side closing/erroring tears down both ---
  proxySocket.on('error', (err) => {
    console.error(`❌ Raw WS relay error for ${req.url}:`, err.message);
    if (!socket.destroyed) socket.destroy();
  });

  socket.on('error', () => {
    if (!proxySocket.destroyed) proxySocket.destroy();
  });

  socket.on('close', () => {
    if (!proxySocket.destroyed) proxySocket.destroy();
  });

  proxySocket.on('close', () => {
    if (!socket.destroyed) socket.destroy();
  });
}

app.prepare().then(() => {
  const nextjsUpgradeHandler = app.getUpgradeHandler();

  const server = createServer(async (req, res) => {
    try {
      const parsedUrl = parse(req.url, true);
      const { pathname } = parsedUrl;

      // Email/password auth endpoints go to backend
      const backendAuthRoutes = [
        '/api/auth/login',
        '/api/auth/register', 
        '/api/auth/validate',
        '/api/auth/verify-invitation'
      ];
      
      if (backendAuthRoutes.some(route => pathname.startsWith(route))) {
        console.log(`🔑 Backend Auth: ${req.method} ${pathname}`);
        apiProxy(req, res);
      } else if (pathname.startsWith('/api/auth/')) {
        // NextAuth routes (session, providers, etc.)
        console.log(`🔐 NextAuth: ${req.method} ${pathname}`);
        await handle(req, res, parsedUrl);
      } else if (pathname.startsWith('/api/') || pathname.startsWith('/uploads/')) {
        apiProxy(req, res);
      } else {
        await handle(req, res, parsedUrl);
      }
    } catch (err) {
      console.error('Error occurred handling', req.url, err);
      res.statusCode = 500;
      res.end('internal server error');
    }
  });

  server.on('upgrade', (req, socket, head) => {
    if (req.url && req.url.startsWith('/api/ws/')) {
      console.log(`🔌 WebSocket upgrade (raw relay): ${req.url} → ${backendUrl}`);
      relayWebSocket(req, socket, head);
    } else {
      nextjsUpgradeHandler(req, socket, head);
    }
  });

  server.listen(port, hostname, (err) => {
    if (err) throw err;
    console.log(`✅ Custom Next.js server ready on http://${hostname}:${port}`);
    console.log(`🔧 Proxying HTTP /api/* to ${backendUrl}`);
    console.log(`🔌 Raw WebSocket relay /api/ws/* → ${backendUrl} (TCP_NODELAY)`);
  });
});
