// Node test: toast stack + theme bootstrap.
//
// Yêu cầu:
//  - Có khay toast riêng, nạp trước app.js, không dùng inline script (CSP 'self').
//  - Toast có animation vào/ra, thanh đếm giờ, đóng tay và chống trùng lặp.
//  - Theme được áp trong <head> trước lần vẽ đầu để không nháy nền.
//  - showNotice vẫn giữ hành vi cũ (ghi vào #notice) và đẩy thêm toast.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const read = (...parts) => fs.readFileSync(path.join(ROOT, ...parts), 'utf8');

const html = read('ui/renderer/index.html');
const css = read('ui/renderer/styles.css');
const app = read('ui/renderer/app.js');
const toast = read('ui/renderer/toast.js');
const theme = read('ui/renderer/theme.js');

test('the toast stack is declared in the markup and bootstrapped before app.js', () => {
  assert.match(html, /id="toast-stack"/);
  const toastAt = html.indexOf('src="toast.js"');
  const appAt = html.indexOf('src="app.js"');
  assert.ok(toastAt > 0 && appAt > toastAt, 'toast.js must load before app.js');
});

test('no inline script is introduced (CSP stays script-src self)', () => {
  assert.match(html, /script-src 'self'/);
  const inline = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>[\s\S]*?<\/script>/g)]
    .filter((match) => match[0].replace(/<\/?script[^>]*>/g, '').trim());
  assert.equal(inline.length, 0, 'inline scripts are blocked by the CSP');
});

test('toast.js exposes a typed API and never throws on empty input', () => {
  assert.match(toast, /window\.aibcrToast = \{/);
  for (const method of ['show:', 'success:', 'error:', 'warning:', 'info:', 'dismissAll:']) {
    assert.ok(toast.includes(method), `missing ${method}`);
  }
  assert.match(toast, /if \(!text\) return null;/);
});

test('toasts animate in and out and report urgency to screen readers', () => {
  assert.match(css, /@keyframes toastIn/);
  assert.match(css, /@keyframes toastOut/);
  assert.match(css, /@keyframes toastProgress/);
  assert.match(toast, /role', type === 'error' \? 'alert' : 'status'/);
});

test('repeats are deduped and the queue is capped', () => {
  assert.match(toast, /TOAST_DEDUPE_MS/);
  assert.match(toast, /TOAST_MAX_VISIBLE/);
  assert.match(toast, /trimToasts/);
});

test('hovering a toast pauses its countdown', () => {
  assert.match(toast, /mouseenter/);
  assert.match(toast, /mouseleave/);
  assert.match(css, /animation-play-state: paused/);
});

test('every toast type has its own accent colour in both themes', () => {
  for (const type of ['success', 'error', 'warning', 'info']) {
    assert.match(css, new RegExp(`\\.toast-${type} \\{ --toast-accent:`));
  }
  assert.match(css, /:root\[data-theme="light"\]/);
});

test('the theme is applied in <head> before the first paint', () => {
  const themeAt = html.indexOf('src="theme.js"');
  const firstPaint = html.indexOf('<body');
  assert.ok(themeAt > 0 && themeAt < firstPaint, 'theme.js must run in <head>');
  assert.match(theme, /aibcr\.theme/);
  assert.match(theme, /dataset\.theme = next/);
  assert.match(html, /<html lang="vi" data-theme="dark">/);
});

test('showNotice still drives the inline notice and adds a toast', () => {
  const body = app.slice(app.indexOf('function showNotice'));
  const fn = body.slice(0, body.indexOf('\n}\n') + 3);
  assert.match(fn, /notice\.textContent = message/);
  assert.match(fn, /notice\.dataset\.state = isError \? 'error' : 'ready'/);
  assert.match(fn, /toast\.error\(text\)/);
  assert.match(fn, /toast\.info\(text\)/);
});

test('the renderer keeps the theme key in sync with theme.js', () => {
  const appKey = /const THEME_KEY = '([^']+)'/.exec(app);
  const moduleKey = /const BCR_THEME_KEY = '([^']+)'/.exec(theme);
  assert.ok(appKey && moduleKey);
  assert.equal(appKey[1], moduleKey[1]);
});

test('reduced motion is respected', () => {
  assert.match(css, /prefers-reduced-motion: reduce/);
});
