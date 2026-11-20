const http = require('node:http');
const https = require('node:https');
const net = require('node:net');
const tls = require('node:tls');

function parseProxy(raw) {
  const value = String(raw || '').trim();
  if (!value) return null;
  const schemeMatch = /^([a-z][a-z0-9+.-]*):\/\//i.exec(value);
  let protocol = (schemeMatch ? schemeMatch[1] : 'http').toLowerCase();
  if (protocol === 'socks5h') protocol = 'socks5';
  const body = schemeMatch ? value.slice(schemeMatch[0].length) : value;
  let host = '';
  let port = 0;
  let username = '';
  let password = '';
  try {
    if (body.includes('@')) {
      const url = new URL(`${protocol}://${body}`);
      host = url.hostname.replace(/^\[|\]$/g, '');
      port = Number(url.port) || (protocol === 'https' ? 443 : protocol === 'http' ? 80 : 0);
      username = decodeURIComponent(url.username || '');
      password = decodeURIComponent(url.password || '');
      if (!['', '/'].includes(url.pathname) || url.search || url.hash) throw new Error('invalid_proxy');
    } else {
      const ipv6 = /^(\[[^\]]+\]):(\d+)(?::([^:]+):(.*))?$/.exec(body);
      if (ipv6) {
        host = ipv6[1].slice(1, -1);
        port = Number(ipv6[2]);
        username = ipv6[3] || '';
        password = ipv6[4] || '';
      } else {
        const parts = body.split(':');
        if (parts.length === 2) [host, port] = parts;
        else if (parts.length >= 4) {
          [host, port, username] = parts;
          password = parts.slice(3).join(':');
        } else throw new Error('invalid_proxy');
        port = Number(port);
      }
      username = decodeURIComponent(username || '');
      password = decodeURIComponent(password || '');
    }
  } catch {
    throw new Error('Dùng host:port:user:pass, http://user:pass@host:port hoặc socks4/socks5://host:port.');
  }
  if (!['http', 'https', 'socks4', 'socks5'].includes(protocol) || !host || !Number.isInteger(port)
      || port < 1 || port > 65535) {
    throw new Error('Proxy cần giao thức, host và port hợp lệ.');
  }
  if (Boolean(username) !== Boolean(password)) {
    throw new Error('Proxy cần đủ tên người dùng và mật khẩu.');
  }
  if (['socks4', 'socks5'].includes(protocol) && (username || password)) {
    throw new Error('SOCKS proxy chỉ hỗ trợ kiểu không có xác thực.');
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

function checkProxy(proxy, timeoutMs = 8000) {
  return new Promise((resolve) => {
    let settled = false;
    let socket = null;
    let targetTls = null;
    const timer = setTimeout(() => finish(false, 'Timeout khi kiểm tra proxy.'), timeoutMs);
    const finish = (ok, message) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (targetTls) targetTls.destroy();
      else if (socket) socket.destroy();
      resolve({ ok, message });
    };
    const tunnel = (connectedSocket) => {
      socket = connectedSocket;
      targetTls = tls.connect({ socket: connectedSocket, servername: 'example.com' });
      targetTls.once('secureConnect', () => finish(true, 'HTTPS tunnel hoạt động.'));
      targetTls.once('error', () => finish(false, 'Không tạo được HTTPS tunnel.'));
    };
    const connectHttpProxy = () => {
      const transport = proxy.protocol === 'https' ? https : http;
      const headers = {};
      if (proxy.username) {
        headers['proxy-authorization'] = `Basic ${Buffer.from(`${proxy.username}:${proxy.password}`).toString('base64')}`;
      }
      const request = transport.request({
        host: proxy.host,
        port: proxy.port,
        method: 'CONNECT',
        path: 'example.com:443',
        headers,
        timeout: timeoutMs,
      });
      request.once('connect', (response, proxySocket) => {
        if (response.statusCode !== 200) {
          proxySocket.destroy();
          finish(false, `Proxy trả HTTP ${response.statusCode || 0}.`);
          return;
        }
        tunnel(proxySocket);
      });
      request.once('response', (response) => {
        response.resume();
        finish(false, `Proxy trả HTTP ${response.statusCode || 0}.`);
      });
      request.once('timeout', () => request.destroy(new Error('timeout')));
      request.once('error', () => finish(false, 'Không kết nối được với proxy.'));
      request.end();
    };
    const connectSocks5 = () => {
      socket = net.connect(proxy.port, proxy.host);
      let buffer = Buffer.alloc(0);
      let state = 'greeting';
      socket.once('connect', () => socket.write(Buffer.from([5, 1, 0])));
      const onData = (chunk) => {
        buffer = Buffer.concat([buffer, chunk]);
        if (state === 'greeting' && buffer.length >= 2) {
          if (buffer[0] !== 5 || buffer[1] !== 0) {
            finish(false, 'Proxy SOCKS5 yêu cầu phương thức xác thực không hỗ trợ.');
            return;
          }
          buffer = buffer.subarray(2);
          state = 'connect';
          const host = Buffer.from('example.com');
          socket.write(Buffer.concat([Buffer.from([5, 1, 0, 3, host.length]), host, Buffer.from([1, 187])]));
        }
        if (state === 'connect' && buffer.length >= 5) {
          if (buffer[0] !== 5 || buffer[1] !== 0) {
            finish(false, 'Proxy SOCKS5 không cho phép kết nối HTTPS.');
            return;
          }
          const addrLength = buffer[3] === 1 ? 4 : buffer[3] === 4 ? 16 : (buffer[4] + 1);
          const replyLength = 4 + addrLength + 2;
          if (buffer.length >= replyLength) {
            state = 'tunnel';
            socket.removeListener('data', onData);
            tunnel(socket);
          }
        }
      };
      socket.on('data', onData);
      socket.once('error', () => finish(false, 'Không kết nối được với proxy SOCKS5.'));
    };

    const connectSocks4 = () => {
      socket = net.connect(proxy.port, proxy.host);
      let buffer = Buffer.alloc(0);
      const domain = Buffer.from('example.com\0');
      const request = Buffer.concat([Buffer.from([4, 1, 1, 187, 0, 0, 0, 1, 0]), domain]);
      const onData = (chunk) => {
        buffer = Buffer.concat([buffer, chunk]);
        if (buffer.length < 8) return;
        socket.removeListener('data', onData);
        if (buffer[1] !== 0x5a) {
          finish(false, 'Proxy SOCKS4 không cho phép kết nối HTTPS.');
          return;
        }
        tunnel(socket);
      };
      socket.once('connect', () => socket.write(request));
      socket.on('data', onData);
      socket.once('error', () => finish(false, 'Không kết nối được với proxy SOCKS4.'));
    };

    if (proxy.protocol === 'socks4') connectSocks4();
    else if (proxy.protocol === 'socks5') connectSocks5();
    else connectHttpProxy();
  });
}

module.exports = { parseProxy, proxyLabel, startProxyBridge, checkProxy };
