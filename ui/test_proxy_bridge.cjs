const assert = require('node:assert/strict');
const http = require('node:http');
const { parseProxy, checkProxy } = require('./proxy_bridge');

async function main() {
  const plain = parseProxy('127.0.0.1:8080');
  assert.equal(plain.protocol, 'http');
  assert.equal(plain.port, 8080);
  const auth = parseProxy('http://worker:secret@127.0.0.1:8080');
  assert.equal(auth.username, 'worker');
  assert.equal(auth.password, 'secret');
  const colonPassword = parseProxy('http://127.0.0.1:8080:worker:part:two');
  assert.equal(colonPassword.password, 'part:two');
  assert.equal(parseProxy('socks4://127.0.0.1:1080').protocol, 'socks4');
  assert.equal(parseProxy('http://[::1]:8080').host, '::1');
  assert.throws(() => parseProxy('socks5://worker:secret@127.0.0.1:8080'));

  let sawAuthorization = false;
  const server = http.createServer();
  server.on('connect', (request, socket) => {
    sawAuthorization = request.headers['proxy-authorization'] ===
      `Basic ${Buffer.from('worker:secret').toString('base64')}`;
    socket.end('HTTP/1.1 407 Proxy Authentication Required\r\n\r\n');
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const result = await checkProxy({ ...auth, host: '127.0.0.1', port: server.address().port }, 1000);
    assert.equal(result.ok, false);
    assert.match(result.message, /HTTP 407/);
    assert.equal(sawAuthorization, true);
    assert.equal(result.message.includes('secret'), false);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
  console.log('proxy bridge tests passed');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
