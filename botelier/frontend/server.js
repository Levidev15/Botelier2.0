const { createServer } = require('http');
const { parse } = require('url');
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

const wsProxy = createProxyMiddleware({
  target: backendUrl,
  changeOrigin: true,
  ws: true,
  logLevel: 'silent',
  on: {
    error: (err, req, socket) => {
      console.error(`❌ WebSocket proxy error for ${req?.url}:`, err.message);
      if (socket && socket.writable) socket.destroy();
    },
  },
});

app.prepare().then(() => {
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
      console.log(`🔌 WebSocket upgrade: ${req.url} → ${backendUrl}`);
      wsProxy.upgrade(req, socket, head);
    } else {
      socket.destroy();
    }
  });

  server.listen(port, hostname, (err) => {
    if (err) throw err;
    console.log(`✅ Custom Next.js server ready on http://${hostname}:${port}`);
    console.log(`🔧 Proxying HTTP /api/* to ${backendUrl}`);
    console.log(`🔌 Proxying WebSocket /api/ws/* to ${backendUrl}`);
  });
});
