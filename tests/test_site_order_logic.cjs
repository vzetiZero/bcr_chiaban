// Node test: hành vi thật của reorderSites (hàm thuần trong ui/site_order.js).
//
// Test cũ chỉ so khớp chuỗi trong main.js — nó không chứng minh thứ tự đúng.
// Ở đây gọi thẳng hàm và kiểm mảng kết quả, gồm cả các biên (đầu/cuối danh
// sách) và trường hợp id không tồn tại.

const test = require('node:test');
const assert = require('node:assert');
const path = require('path');

const { reorderSites, SITE_ORDER_ACTIONS } = require(path.join(__dirname, '..', 'ui', 'site_order.js'));

const base = () => ([
  { id: 'febet', label: 'FEBET' },
  { id: 'gk881', label: 'GK881' },
  { id: 'e3951', label: 'E3951' },
  { id: 'vnwtop', label: 'VNWTop' },
]);
const ids = (sites) => sites.map((site) => site.id);

test('"top" đưa site lên vị trí 1', () => {
  const result = reorderSites(base(), 'vnwtop', 'top');
  assert.equal(result.ok, true);
  assert.equal(result.moved, true);
  assert.deepEqual(ids(result.sites), ['vnwtop', 'febet', 'gk881', 'e3951']);
  assert.match(result.note, /lên vị trí 1/);
});

test('"up" tăng đúng một vị trí', () => {
  const result = reorderSites(base(), 'e3951', 'up');
  assert.deepEqual(ids(result.sites), ['febet', 'e3951', 'gk881', 'vnwtop']);
  assert.match(result.note, /lên vị trí 2/);
});

test('"down" giảm đúng một vị trí', () => {
  const result = reorderSites(base(), 'gk881', 'down');
  assert.deepEqual(ids(result.sites), ['febet', 'e3951', 'gk881', 'vnwtop']);
  assert.match(result.note, /xuống vị trí 3/);
});

test('không làm thay đổi mảng gốc (không mutate)', () => {
  const sites = base();
  const snapshot = ids(sites);
  reorderSites(sites, 'vnwtop', 'top');
  assert.deepEqual(ids(sites), snapshot);
});

test('site đã ở đầu: "top" và "up" trả moved:false, giữ nguyên thứ tự', () => {
  for (const action of ['top', 'up']) {
    const result = reorderSites(base(), 'febet', action);
    assert.equal(result.ok, true);
    assert.equal(result.moved, false);
    assert.deepEqual(ids(result.sites), ids(base()));
    assert.match(result.note, /FEBET/);
  }
});

test('site đã ở cuối: "down" trả moved:false, giữ nguyên thứ tự', () => {
  const result = reorderSites(base(), 'vnwtop', 'down');
  assert.equal(result.ok, true);
  assert.equal(result.moved, false);
  assert.deepEqual(ids(result.sites), ids(base()));
  assert.match(result.note, /cuối danh sách/);
});

test('id không tồn tại là lỗi', () => {
  const result = reorderSites(base(), 'khong-co', 'up');
  assert.equal(result.ok, false);
  assert.match(result.error, /Không tìm thấy site/);
});

test('thao tác lạ bị từ chối', () => {
  for (const action of ['', 'first', 'TOP1', null, undefined]) {
    const result = reorderSites(base(), 'e3951', action);
    assert.equal(result.ok, false, `action ${action} phải bị từ chối`);
    assert.match(result.error, /không hợp lệ/);
  }
});

test('id và action không phân biệt hoa thường, bỏ khoảng trắng', () => {
  const result = reorderSites(base(), '  VNWTOP ', ' TOP ');
  assert.equal(result.ok, true);
  assert.equal(result.sites[0].id, 'vnwtop');
});

test('danh sách một site: mọi thao tác đều là biên', () => {
  const one = [{ id: 'febet', label: 'FEBET' }];
  for (const action of SITE_ORDER_ACTIONS) {
    const result = reorderSites(one, 'febet', action);
    assert.equal(result.ok, true);
    assert.equal(result.moved, false);
    assert.deepEqual(ids(result.sites), ['febet']);
  }
});

test('sắp xếp nhiều lần liên tiếp vẫn đúng thứ tự', () => {
  let sites = base();
  sites = reorderSites(sites, 'vnwtop', 'top').sites;
  assert.deepEqual(ids(sites), ['vnwtop', 'febet', 'gk881', 'e3951']);
  sites = reorderSites(sites, 'e3951', 'top').sites;
  assert.deepEqual(ids(sites), ['e3951', 'vnwtop', 'febet', 'gk881']);
  sites = reorderSites(sites, 'e3951', 'down').sites;
  assert.deepEqual(ids(sites), ['vnwtop', 'e3951', 'febet', 'gk881']);
});

test('site thiếu label vẫn có lời nhắn dùng id', () => {
  const sites = [{ id: 'a1' }, { id: 'b2' }];
  const result = reorderSites(sites, 'b2', 'top');
  assert.match(result.note, /b2/);
});

test('đầu vào không phải mảng thì báo không tìm thấy, không ném lỗi', () => {
  for (const value of [null, undefined, 'abc', 42]) {
    const result = reorderSites(value, 'febet', 'up');
    assert.equal(result.ok, false);
    assert.match(result.error, /Không tìm thấy site/);
  }
});
