const http = require('node:http');
const https = require('node:https');
const net = require('node:net');
const tls = require('node:tls');

function parseProxy(raw) {
  const value = String(raw || '').trim();
  if (!value) return null;
  let url;
  try {
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) url = new URL(value);
    else {
      const parts = value.split(':');
      if (parts.length === 2) url = new URL(`http://${value}`);
      else if (parts.length === 4) {
        url = new URL(`http://${encodeURIComponent(parts[2])}:${encodeURIComponent(parts[3])}@${parts[0]}:${parts[1]}`);
      } else throw new Error('invalid_proxy');
    }
  } catch {
    throw new Error('Dùng http://host:port, http://user:pass@host:port, socks5://host:port hoặc host:port:user:pass.');
  }
  let protocol = url.protocol.slice(0, -1).toLowerCase();
  if (protocol === 'socks5h') protocol = 'socks5';
  const port = Number(url.port) || (protocol === 'https' ? 443 : protocol === 'http' ? 80 : 0);
  const host = url.hostname.replace(/^\[|\]$/g, '');
  let username = '';
  let password = '';
  try {
    username = decodeURIComponent(url.username || '');
    password = decodeURIComponent(url.password || '');
  } catch {
    throw new Error('Thông tin xác thực proxy có định dạng không hợp lệ.');
  }
  if (!['http', 'https', 'socks5'].includes(protocol) || !host || !Number.isInteger(port)
      || port < 1 || port > 65535 || !['', '/'].includes(url.pathname) || url.search || url.hash) {
    throw new Error('Proxy cần giao thức, host và port hợp lệ.');
  }
  if (Boolean(username) !== Boolean(password)) {
    throw new Error('Proxy cần đủ tên người dùng và mật khẩu.');
  }
  if (protocol === 'socks5' && (username || password)) {
    throw new Error('SOCKS5 chỉ hỗ trợ proxy không có xác thực.');
  }
  return { protocol, host, port, username, password };
}

function proxyLabel(proxy) {
  if (!proxy) return 'IP trực tiếp';
  const host = proxy.host.includes(':') ? `[${proxy.host}]` : proxy.host;
  return `${proxy.protocol}://${host}:${proxy.port}${proxy.username ? ' (auth)' : ''}`;
}

function startProxyBridge(upstream) {
  if (!['http', 'https'].includes(upstream.protocol) || !upstream.username) {
    throw new Error('Bridge chỉ dùng cho proxy HTTP/HTTPS có xác thực.');
  }
  const auth = `Basic ${Buffer.from(`${upstream.username}:${upstream.password}`).toString('base64')}`;
  const sockets = new Set();

  const server = http.createServer((request, response) => {
    if (!/^http:\/\//i.test(request.url || '')) {
      response.writeHead(400, { 'content-type': 'text/plain; charset=utf-8' });
      response.end('Unsupported proxy request.');
      return;
    }
    const headers = { ...request.headers, 'proxy-authorization': auth };
    delete headers['proxy-connection'];
    delete headers.connection;
    const transport = upstream.protocol === 'https' ? https : http;
    const outgoing = transport.request({
      host: upstream.host,
      port: upstream.port,
      method: request.method,
      path: request.url,
      headers,
    }, (incoming) => {
      response.writeHead(incoming.statusCode || 502, incoming.headers);
      incoming.pipe(response);
    });
    outgoing.on('error', () => {
      if (!response.headersSent) response.writeHead(502);
      response.end('Upstream proxy error.');
    });
    request.pipe(outgoing);
  });

  server.on('connection', (socket) => {
    sockets.add(socket);
    socket.once('close', () => sockets.delete(socket));
  });

  server.on('connect', (request, client, head) => {
    const split = String(request.url || '').lastIndexOf(':');
    const host = split > 0 ? request.url.slice(0, split) : '';
    const port = split > 0 ? Number(request.url.slice(split + 1)) : 0;
    if (!host || !Number.isInteger(port) || port < 1 || port > 65535) {
      client.end('HTTP/1.1 400 Bad Request\r\n\r\n');
      return;
    }
    const targetHost = host.startsWith('[') && host.endsWith(']') ? host.slice(1, -1) : host;
    const remote = upstream.protocol === 'https'
      ? tls.connect({ host: upstream.host, port: upstream.port, servername: upstream.host })
      : net.connect({ host: upstream.host, port: upstream.port });
    client.on('error', () => remote.destroy());
    let settled = false;
    let received = Buffer.alloc(0);
    const fail = () => {
      if (settled) return;
      settled = true;
      remote.destroy();
      if (client.writable) client.end('HTTP/1.1 502 Bad Gateway\r\n\r\n');
    };
    remote.once('error', fail);
    const sendConnect = () => remote.write([
      `CONNECT ${targetHost}:${port} HTTP/1.1`,
      `Host: ${targetHost}:${port}`,
      `Proxy-Authorization: ${auth}`,
      'Connection: keep-alive',
      '',
      '',
    ].join('\r\n'));
    if (upstream.protocol === 'https') remote.once('secureConnect', sendConnect);
    else remote.once('connect', sendConnect);
    remote.on('data', (chunk) => {
      if (settled) return;
      received = Buffer.concat([received, chunk]);
      const end = received.indexOf('\r\n\r\n');
      if (end < 0) {
        if (received.length > 65536) fail();
        return;
      }
      const header = received.subarray(0, end).toString('latin1');
      const status = Number((header.split('\r\n')[0] || '').split(/\s+/)[1]);
      const remainder = received.subarray(end + 4);
      if (status !== 200) {
        fail();
        return;
      }
      settled = true;
      remote.removeAllListeners('data');
      client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (head.length) client.write(head);
      if (remainder.length) client.write(remainder);
      remote.pipe(client);
      client.pipe(remote);
    });
  });

  return new Promise((resolve, reject) => {
    server.once('error', () => reject(new Error('Không khởi động được proxy bridge cục bộ.')));
    server.listen(0, '127.0.0.1', () => {
      server.unref();
      const address = server.address();
      resolve({
        url: `http://127.0.0.1:${address.port}`,
        close: () => new Promise((done) => {
          for (const socket of sockets) socket.destroy();
          server.close(() => done());
        }),
      });
    });
  });
}

module.exports = { parseProxy, proxyLabel, startProxyBridge };
