// Node test: thứ tự site trong tab Cấu hình là thật, không chỉ là hiển thị.
//
// Tab Cấu hình cho phép đưa một site lên vị trí 1, tăng 1 vị trí hoặc giảm 1 vị
// trí. Thứ tự đó phải được lưu vào sites-config.json (nên lần mở app sau vẫn
// còn) và phải là thứ tự option trong dropdown chọn site của từng Profile, nếu
// không người dùng thấy hai danh sách lệch nhau.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const main = fs.readFileSync(path.join(ROOT, 'ui', 'main.js'), 'utf8');
const preload = fs.readFileSync(path.join(ROOT, 'ui', 'preload.js'), 'utf8');
const html = fs.readFileSync(path.join(ROOT, 'ui', 'renderer', 'index.html'), 'utf8');
const app = fs.readFileSync(path.join(ROOT, 'ui', 'renderer', 'app.js'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'ui', 'renderer', 'styles.css'), 'utf8');

test('có IPC sites:reorder và preload expose reorderSite', () => {
  assert.ok(main.includes("ipcMain.handle('sites:reorder'"), 'thiếu IPC sites:reorder');
  assert.match(preload, /reorderSite: \(id, action\) => ipcRenderer\.invoke\('sites:reorder'/);
});

test('handler uỷ quyền cho hàm thuần reorderSites (có test hành vi riêng)', () => {
  const start = main.indexOf("ipcMain.handle('sites:reorder'");
  const body = main.slice(start, main.indexOf("\nipcMain.handle('sites:delete'", start));
  assert.match(body, /reorderSites\(sitesConfig\(\), id, action\)/);
  assert.match(body, /if \(!result\.ok\) return result/);
  // Chỉ ghi file khi thứ tự thật sự đổi.
  assert.match(body, /if \(result\.moved\) await saveSitesConfig\(result\.sites\)/);
  assert.match(body, /moved: result\.moved/);
});

test('hàm thuần reorderSites nằm ở module riêng và được require', () => {
  assert.match(main, /require\('\.\/site_order'\)/);
  const mod = fs.readFileSync(path.join(ROOT, 'ui', 'site_order.js'), 'utf8');
  assert.match(mod, /function reorderSites\(sites, id, action\)/);
  assert.match(mod, /module\.exports = \{ reorderSites/);
  // Biên danh sách trả moved:false thay vì ném lỗi.
  assert.match(mod, /moved: false/);
  assert.match(mod, /đã ở đầu danh sách/);
  assert.match(mod, /đã ở cuối danh sách/);
  assert.match(mod, /đã ở vị trí 1/);
});

test('renderer có hàm reorderSite dùng API mới', () => {
  assert.match(app, /async function reorderSite\(site, action\)/);
  const body = app.slice(app.indexOf('async function reorderSite('));
  assert.match(body.slice(0, 900), /api\.reorderSite\(site\.id, action\)/);
});

test('renderer vẽ nút lên đầu / lên 1 / xuống 1 cho mỗi site', () => {
  const start = app.indexOf('function renderSiteConfig(');
  const body = app.slice(start, app.indexOf('function setSiteFormNote('));
  assert.match(body, /reorderSite\(site, 'top'\)/);
  assert.match(body, /reorderSite\(site, 'up'\)/);
  assert.match(body, /reorderSite\(site, 'down'\)/);
  assert.match(body, /site-config-order-badge/);
});

test('nút sắp xếp bị khoá ở vị trí biên', () => {
  const start = app.indexOf('function renderSiteConfig(');
  const body = app.slice(start, app.indexOf('function setSiteFormNote('));
  assert.match(body, /toTop\.disabled = position === 1/);
  assert.match(body, /up\.disabled = position === 1/);
  assert.match(body, /down\.disabled = position === siteRows\.length/);
});

test('sắp xếp xong thì dropdown của profile đồng bộ lại thứ tự', () => {
  const start = app.indexOf('async function reorderSite(');
  const body = app.slice(start, start + 1200);
  assert.match(body, /profileSites = result\.sites/);
  assert.match(body, /renderSiteConfig\(profileSites\)/);
  assert.match(body, /syncProfileSiteOptions\(\)/);
});

test('dropdown profile lấy đúng thứ tự từ profileSites (không sort lại)', () => {
  // sort lại sẽ làm thứ tự người dùng chọn bị ghi đè ngay khi render.
  assert.doesNotMatch(app, /profileSites\.slice\(\)\.sort/);
  const sync = app.slice(app.indexOf('function syncProfileSiteOptions('));
  assert.match(sync.slice(0, 900), /for \(const site of profileSites\)/);
});

test('CSS có style cho cột thứ tự và nút di chuyển', () => {
  assert.ok(css.includes('.site-config-order-badge'), 'thiếu .site-config-order-badge');
  assert.ok(css.includes('.site-move'), 'thiếu .site-move');
  assert.match(css, /grid-template-columns: auto minmax\(0, 1fr\) auto/);
});

test('hướng dẫn sắp xếp có trong tab Cấu hình', () => {
  assert.match(html, /site-config-note/);
  assert.match(html, /vị trí 1/);
});
