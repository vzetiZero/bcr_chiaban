// Node test: the site list is a CRUD store, not a hardcoded array.
//
// Users must be able to edit each site's URL, add sites, delete sites and reset
// to defaults, because casino portals change their links.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const main = fs.readFileSync(path.join(ROOT, 'ui', 'main.js'), 'utf8');
const preload = fs.readFileSync(path.join(ROOT, 'ui', 'preload.js'), 'utf8');
const html = fs.readFileSync(path.join(ROOT, 'ui', 'renderer', 'index.html'), 'utf8');
const app = fs.readFileSync(path.join(ROOT, 'ui', 'renderer', 'app.js'), 'utf8');

test('sites live in an editable store seeded from defaults', () => {
  assert.match(main, /const DEFAULT_SITES = Object\.freeze\(\[/);
  assert.match(main, /sites-config\.json/);
  assert.match(main, /function sitesConfig\(\)/);
  assert.match(main, /async function saveSitesConfig\(sites\)/);
});

test('a site has id, label, url, chip group and automation flag', () => {
  const block = main.slice(main.indexOf('const DEFAULT_SITES'), main.indexOf('const SITE_ID_RE'));
  for (const field of ['id:', 'label:', 'url:', 'chips:', 'auto:']) {
    assert.ok(block.includes(field), `missing field ${field}`);
  }
});

test('CRUD IPC handlers exist', () => {
  for (const channel of ['sites:list', 'sites:create', 'sites:update', 'sites:delete', 'sites:reset']) {
    assert.ok(main.includes(`ipcMain.handle('${channel}'`), `missing ${channel}`);
  }
});

test('preload exposes the CRUD API', () => {
  for (const api of ['listSites', 'createSite', 'updateSite', 'deleteSite', 'resetSites']) {
    assert.ok(preload.includes(api), `missing ${api}`);
  }
});

test('site ids are validated and duplicates rejected', () => {
  assert.match(main, /const SITE_ID_RE = \/\^\[a-z0-9\]/);
  assert.match(main, /đã tồn tại/);
});

test('only https URLs are accepted', () => {
  assert.match(main, /parsed\.protocol !== 'https:'/);
  assert.match(main, /bắt đầu bằng https:\/\//);
});

test('the last site cannot be deleted', () => {
  assert.match(main, /Phải giữ lại ít nhất một site/);
});

test('auto entry comes from site metadata, not a hardcoded list', () => {
  assert.match(main, /const autoEntryIndices = indicesToUse\.filter/);
  assert.match(main, /meta\?\.auto/);
  // The old hardcoded site list must be gone from the run gate.
  assert.doesNotMatch(main, /\['febet', 'gk881', 'e3951', 'vnwtop'\]\.includes\(siteFor\(index\)\)/);
});

test('the Config tab exists with its controls', () => {
  assert.match(html, /data-tab-target="config"/);
  assert.match(html, /data-tab-panel="config"/);
  assert.match(html, /id="site-config-list"/);
  assert.match(html, /id="site-form"/);
  assert.match(html, /id="site-add"/);
  assert.match(html, /id="site-reset"/);
});

test('the renderer renders and edits sites', () => {
  assert.match(app, /function renderSiteConfig\(sites\)/);
  assert.match(app, /function openSiteForm\(site/);
  assert.match(app, /async function saveSiteFromForm\(event\)/);
  assert.match(app, /async function deleteSite\(site\)/);
  assert.match(app, /function syncProfileSiteOptions\(\)/);
});

test('per-profile dropdowns follow the editable list', () => {
  assert.match(app, /syncProfileSiteOptions\(\);\n  renderProfiles/);
});

test('removing a site clears stale per-profile selections', () => {
  const block = app.slice(app.indexOf('function syncProfileSiteOptions'));
  assert.match(block.slice(0, 1200), /profileSiteSelections\[String\(select\.dataset\.profile\)\]/);
});

test('app branding is ChiaBanBCR, not AI BCR', () => {
  assert.match(html, /<title>ChiaBanBCR<\/title>/);
  assert.doesNotMatch(html, /AI BCR/);
  assert.doesNotMatch(main, /AI_BCR Desktop/);
});
