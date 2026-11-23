// Node test: tab Profiles chia thành 3 tab con (Chrome / OmniLogin / Hidemium).
//
// Kiểm tra phần markup + renderer của tab con: mỗi provider có đủ nút kết nối,
// gán, mở/đóng và ô tìm kiếm; việc chuyển tab chỉ hiện một pane; trạng thái tab
// được nhớ lại; và các lệnh mở/đóng dùng chung IPC profile:open / profile:close.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const HTML = path.join(ROOT, 'ui', 'renderer', 'index.html');
const RENDERER = path.join(ROOT, 'ui', 'renderer', 'app.js');
const CSS = path.join(ROOT, 'ui', 'renderer', 'styles.css');

const html = fs.readFileSync(HTML, 'utf8');
const renderer = fs.readFileSync(RENDERER, 'utf8');
const css = fs.readFileSync(CSS, 'utf8');

const SUBTABS = ['chrome', 'omni', 'hidemium'];
const PROVIDERS = {
  omni: { label: 'OmniLogin', source: 'omni' },
  hidemium: { label: 'Hidemium', source: 'hidemium' },
};

test('tab bar có đúng 3 tab con và 3 pane tương ứng', () => {
  for (const name of SUBTABS) {
    assert.match(html, new RegExp(`data-subtab-target="${name}"`), `thiếu nút tab ${name}`);
    assert.match(html, new RegExp(`data-subtab-panel="${name}"`), `thiếu pane ${name}`);
  }
  const targets = [...html.matchAll(/data-subtab-target="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(targets, SUBTABS);
  const panels = [...html.matchAll(/data-subtab-panel="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(panels, SUBTABS);
});

test('chỉ một pane được đánh dấu active lúc ban đầu', () => {
  const activePanels = [...html.matchAll(/class="subtab-panel[^"]*active[^"]*"[^>]*data-subtab-panel="(\w+)"/g)]
    .map((m) => m[1]);
  assert.deepEqual(activePanels, ['chrome']);
});

test('mỗi provider có đủ điều khiển kết nối, gán, mở và đóng', () => {
  for (const key of Object.keys(PROVIDERS)) {
    for (const suffix of ['api-url', 'search', 'status', 'refresh', 'assign-all',
      'open-all', 'close-all', 'clear', 'notice', 'profile-assignments']) {
      assert.ok(html.includes(`id="${key}-${suffix}"`), `thiếu #${key}-${suffix}`);
    }
  }
});

test('badge đếm profile trên từng tab con', () => {
  for (const name of SUBTABS) {
    assert.ok(html.includes(`id="subtab-count-${name}"`), `thiếu badge ${name}`);
  }
});

test('renderer dùng chung một mô hình provider thay vì lặp code', () => {
  assert.match(renderer, /const PROVIDERS = \{/);
  for (const key of Object.keys(PROVIDERS)) {
    assert.match(renderer, new RegExp(`${key}: \\{[^}]*label:`), `PROVIDERS thiếu ${key}`);
  }
  assert.match(renderer, /function renderProviderAssignments\(key/);
  assert.match(renderer, /for \(const key of Object\.keys\(PROVIDERS\)\)/);
});

test('trạng thái tab con được nhớ trong localStorage', () => {
  assert.match(renderer, /const PROFILE_SUBTAB_KEY = 'aibcr\.profileSubtab'/);
  assert.match(renderer, /localStorage\.setItem\(PROFILE_SUBTAB_KEY/);
  assert.match(renderer, /localStorage\.getItem\(PROFILE_SUBTAB_KEY/);
});

test('setProfileSubtab ẩn/hiện pane và cập nhật aria-selected', () => {
  const start = renderer.indexOf('function setProfileSubtab(');
  assert.ok(start > 0, 'không tìm thấy setProfileSubtab');
  const body = renderer.slice(start, renderer.indexOf('\n}\n', start));
  assert.match(body, /classList\.toggle\('active'/);
  assert.match(body, /aria-selected/);
  assert.match(body, /\[data-subtab-panel\]/);
});

test('mở/đóng trên tab provider dùng chung IPC profile:open và profile:close', () => {
  assert.match(renderer, /api\.openProfile\(index, MAX_PROFILES, collectSettings/);
  assert.match(renderer, /api\.closeProfile\(index\)/);
  const toggle = renderer.slice(renderer.indexOf('async function toggleProviderProfile('));
  assert.match(toggle, /spec\.source/);
});

test('mở tất cả profile provider chạy tuần tự để không nghẽn cổng', () => {
  const body = renderer.slice(renderer.indexOf('async function openAllProviderProfiles('),
    renderer.indexOf('async function closeAllProviderProfiles('));
  assert.match(body, /for \(const index of indices\)/);
  assert.doesNotMatch(body, /Promise\.all\(/);
});

test('chọn nguồn profile ở tab Chạy Tool sẽ nhảy sang tab con tương ứng', () => {
  const body = renderer.slice(renderer.indexOf("$('#profile-source').addEventListener"));
  assert.match(body.slice(0, 900), /setProfileSubtab\(/);
});

test('nút chọn tất cả / bỏ chọn / mở đã chọn / đóng tất cả có trong tab Chrome', () => {
  for (const id of ['profile-select-all', 'profile-select-none', 'profile-open-selected',
    'profile-close-all']) {
    assert.ok(html.includes(`id="${id}"`), `thiếu #${id}`);
  }
});

test('CSS có style cho tab con và thẻ provider', () => {
  for (const selector of ['.subtab-bar', '.subtab-nav', '.subtab-button', '.subtab-panel',
    '.provider-card', '.provider-toolbar', '.provider-assignment']) {
    assert.ok(css.includes(selector), `thiếu ${selector}`);
  }
  // Tab con phải giữ được bố cục ngang ở cửa sổ hẹp.
  assert.match(css, /@media \(max-width: 860px\)/);
});

test('không có script nội tuyến trong index.html (CSP script-src self)', () => {
  const inline = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>/gi)];
  assert.equal(inline.length, 0, 'index.html không được có <script> nội tuyến');
});
