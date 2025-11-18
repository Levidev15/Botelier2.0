const { createServer } = require('http');
const { parse } = require('url');
const next = require('next');
const { createProxyMiddleware } = require('http-proxy-middleware');

const dev = process.env.NODE_ENV !== 'production';
const hostname = '0.0.0.0';
const port = parseInt(process.env.PORT || '5000', 10);

const app = next({ dev, hostname, port });
const handle = app.getRequestHandler();

app.prepare().then(() => {
  const server = createServer(async (req, res) => {
    try {
      const parsedUrl = parse(req.url, true);
      const { pathname } = parsedUrl;

      if (pathname.startsWith('/api/')) {
        const apiProxy = createProxyMiddleware({
          target: 'http://localhost:3001',
          changeOrigin: true,
          ws: true,
          logLevel: 'debug',
          onProxyReq: (proxyReq, req, res) => {
            console.log(`🔄 Proxying ${req.method} ${req.url} to backend`);
          },
          onProxyReqWs: (proxyReq, req, socket, options, head) => {
            console.log(`🔌 Proxying WebSocket ${req.url} to backend`);
          },
          onError: (err, req, res) => {
            console.error(`❌ Proxy error for ${req.url}:`, err.message);
            if (res.writeHead) {
              res.writeHead(500, { 'Content-Type': 'text/plain' });
              res.end('Proxy error');
            }
          }
        });

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
    const { pathname } = parse(req.url, true);
    
    console.log(`⬆️ WebSocket upgrade request: ${pathname}`);
    
    if (pathname.startsWith('/api/')) {
      const wsProxy = createProxyMiddleware({
        target: 'http://localhost:3001',
        changeOrigin: true,
        ws: true,
        logLevel: 'debug'
      });

      wsProxy.upgrade(req, socket, head);
    } else {
      socket.destroy();
    }
  });

  server.listen(port, hostname, (err) => {
    if (err) throw err;
    console.log(`✅ Custom Next.js server ready on http://${hostname}:${port}`);
    console.log(`🔧 Proxying /api/* to http://localhost:3001`);
    console.log(`🔌 WebSocket upgrade support enabled for /api/*`);
  });
});
