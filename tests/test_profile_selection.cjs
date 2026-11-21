// Node test: flexible profile selection plumbing in the Electron main process.
//
// The renderer picks an arbitrary set of profile indices (for example P1 and P3).
// This test verifies the main-process helpers accept that list instead of
// assuming the contiguous 1..N range.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const MAIN = path.join(__dirname, '..', 'ui', 'main.js');
const source = fs.readFileSync(MAIN, 'utf8');

function extractHandler(channel) {
  const marker = `ipcMain.handle('${channel}',`;
  const start = source.indexOf(marker);
  assert.ok(start >= 0, `${channel} handler not found`);
  // The handler body begins at the first `{` after the arrow function params.
  const arrow = source.indexOf('=>', start);
  let i = source.indexOf('{', arrow);
  const from = i;
  let depth = 0;
  for (; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  return source.slice(from, i + 1);
}

function extract(name) {
  const start = source.indexOf(`async function ${name}(`);
  assert.ok(start >= 0, `${name} not found`);
  let depth = 0;
  let i = source.indexOf('{', start);
  const from = i;
  for (; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  return source.slice(start, i + 1);
}

test('profiles:open accepts an explicit index list', () => {
  assert.match(source, /ipcMain\.handle\('profiles:open',[^]*?indices/);
  assert.match(source, /Array\.isArray\(indices\)/);
  const handler = extractHandler('profiles:open');
  assert.match(handler, /requestedIndices/);
  assert.match(handler, /ensureProfileEngine\(\s*requestedIndices\[offset\]/);
});

test('profiles:open maps settings by requested index, not position', () => {
  const handler = extractHandler('profiles:open');
  assert.match(handler, /String\(requestedIndices\[index\]\)/);
  assert.match(handler, /requestedIndices\.includes\(index\)/);
});

test('runDGGroup accepts requested indices and no longer requires 1..N', () => {
  const group = extract('runDGGroup');
  assert.match(group, /requestedIndices = null/);
  assert.match(group, /const missing = wanted\.filter/);
  assert.doesNotMatch(group, /indices\.some\(\(index, offset\) => index !== offset \+ 1\)/);
  assert.match(group, /const indicesToUse = wanted/);
});

test('dg:auto-run forwards the selected indices', () => {
  assert.match(source, /ipcMain\.handle\('dg:auto-run',[^]*?indices[^]*?runDGGroup\(count, siteIds, indices\)/);
});

test('profile sites expose the chip grouping labels', () => {
  assert.match(source, /chips: 'small'/);
  assert.match(source, /chips: 'large'/);
  assert.match(source, /const SITE_CHIP_LABELS = Object\.freeze\(\{/);
  assert.match(source, /small: 'Chip 10'/);
  assert.match(source, /large: 'Chip 100k'/);
});

test('registration publishes the display label for the UI', () => {
  assert.match(source, /display: siteOptionLabel\(\{ label, chips \}\)/);
});

test('large-chip sites are grouped together at the end of the list', () => {
  const block = source.slice(source.indexOf('const PROFILE_SITES'), source.indexOf('const SITE_CHIP_LABELS'));
  const ids = [...block.matchAll(/\{ id: '([^']+)', label: [^}]*chips: '(\w+)'/g)]
    .map((match) => ({ id: match[1], chips: match[2] }));
  assert.ok(ids.length >= 6, 'expected at least six sites');
  const largeIds = ids.filter((site) => site.chips === 'large').map((site) => site.id);
  assert.deepEqual(largeIds, ['vnwtop', 'febet']);
  assert.equal(ids[ids.length - 1].id, 'febet');
});

const RENDERER = path.join(__dirname, '..', 'ui', 'renderer', 'app.js');
const HTML = path.join(__dirname, '..', 'ui', 'renderer', 'index.html');
const renderer = fs.readFileSync(RENDERER, 'utf8');
const html = fs.readFileSync(HTML, 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'ui', 'renderer', 'styles.css'), 'utf8');

test('the numeric account-count input is gone', () => {
  assert.ok(!html.includes('id="profile-count"'), 'count input should be removed');
  assert.ok(!renderer.includes("$('#profile-count')"), 'renderer should not query the count input');
});

test('selection is derived from the picked profiles and can be saved', () => {
  assert.match(html, /id="profile-picker"/);
  assert.match(html, /id="save-profile-selection"/);
  assert.match(renderer, /selection\.length/);
  assert.match(renderer, /PROFILE_SELECTION_KEY/);
});

test('the Profiles tab always lists every profile slot', () => {
  assert.match(renderer, /renderProfiles\(MAX_PROFILES/);
  assert.match(renderer, /const MAX_PROFILES = 8/);
});

test('a dark/light theme toggle exists and is persisted', () => {
  assert.match(html, /id="theme-toggle"/);
  assert.match(renderer, /documentElement\.dataset\.theme/);
  assert.match(renderer, /THEME_KEY/);
  assert.match(css, /:root\[data-theme="light"\]/);
});
