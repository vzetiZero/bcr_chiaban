// Node test: chọn bàn chung cho cả nhóm (ui/table_sync.js).
//
// Nguyên tắc bắt buộc: các profile có thể vào từ site khác nhau nhưng phải vào
// **cùng một bàn DG**. Mã bàn 60xxx là không gian chung của DG, nên bàn hợp lệ
// phải xuất hiện trong danh sách của mọi sảnh. Trước đây code lấy bàn của profile
// dẫn đầu rồi ép các profile khác vào, nên hai site có tập bàn khác nhau sẽ tách
// bàn mà không báo.

const test = require('node:test');
const assert = require('node:assert');
const path = require('path');
const fs = require('fs');

const { normalizeTables, commonTables, pickSharedTable } = require(path.join(__dirname, '..', 'ui', 'table_sync.js'));

const row = (id, online = 0, name = '') => ({ table_id: id, name, online });

test('normalizeTables keeps only real DG baccarat ids', () => {
  const rows = normalizeTables([
    row('60101', 10, 'RB01'),
    row('10101', 999, 'lobby grid'),
    row('', 5),
    row('60abc'),
    row('601010'),
  ]);
  assert.deepEqual(rows.map((item) => item.table_id), ['60101', '601010']);
});

test('normalizeTables deduplicates the same table redrawn by Laya', () => {
  const rows = normalizeTables([row('60101', 10, ''), row('60101', 22, 'RB01')]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].online, 22);
  assert.equal(rows[0].name, 'RB01');
});

test('pickSharedTable uses a table present in every lobby', () => {
  const picked = pickSharedTable([
    [row('60101', 700, 'RB01'), row('60102', 500, 'RB02')],
    [row('60102', 480, 'RB02'), row('60103', 300, 'RB03')],
  ]);
  assert.equal(picked.ok, true);
  assert.equal(picked.table_id, '60102');
  assert.deepEqual(picked.common_ids, ['60102']);
});

test('pickSharedTable refuses to split the group when lobbies do not overlap', () => {
  const picked = pickSharedTable([
    [row('60101', 700, 'RB01')],
    [row('60102', 480, 'RB02')],
  ]);
  assert.equal(picked.ok, false);
  assert.match(picked.error, /Không có bàn DG nào xuất hiện ở cả 2 sảnh/);
});

test('pickSharedTable refuses when one lobby has not listed tables yet', () => {
  const picked = pickSharedTable([[row('60101', 700, 'RB01')], []]);
  assert.equal(picked.ok, false);
  assert.deepEqual(picked.missing, [1]);
});

test('pickSharedTable keeps the group together when two sites name the table differently', () => {
  // Hai site có thể đặt tên bàn khác nhau (RB01 vs Baccarat A) nhưng mã bàn DG
  // phải trùng; đây chính là điều giữ nhóm ở cùng một bàn.
  const picked = pickSharedTable([
    [row('60101', 700, 'Baccarat RB01')],
    [row('60101', 690, 'Baccarat A')],
  ]);
  assert.equal(picked.ok, true);
  assert.equal(picked.table_id, '60101');
  assert.equal(picked.table_name, 'Baccarat RB01');
  assert.equal(picked.online, 690);
});

test('pickSharedTable prefers the table with the most total players', () => {
  const picked = pickSharedTable([
    [row('60101', 100, 'RB01'), row('60102', 400, 'RB02')],
    [row('60101', 900, 'RB01'), row('60102', 300, 'RB02')],
  ]);
  assert.equal(picked.table_id, '60101');
});

test('commonTables keeps the minimum online count so one lobby never overstates', () => {
  const shared = commonTables([
    [row('60101', 700)],
    [row('60101', 20)],
  ]);
  assert.equal(shared[0].online, 20);
  assert.equal(shared[0].total, 720);
});

test('pickSharedTable needs at least one profile', () => {
  assert.equal(pickSharedTable([]).ok, false);
});

test('the group run reads every lobby and syncs the shared table', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'ui', 'main.js'), 'utf8');
  const start = source.indexOf('async function runDGGroup(');
  const body = source.slice(start, source.indexOf("ipcMain.handle('dg:auto-run'"));
  // Mỗi profile tự đọc sảnh của nó...
  assert.match(body, /indices\.map\(\(index\) =>\s*\n?\s*profileEngine\(index\)\.call\('dg\.tables'/);
  // ...rồi giao lại để chọn bàn.
  assert.match(body, /pickSharedTable\(perProfile\)/);
  // Không được quay về "lấy bàn của profile dẫn đầu".
  assert.doesNotMatch(body, /leader\.call\('dg\.tables'/);
  // Xoay bàn chỉ trong phần giao.
  assert.match(body, /startSharedHop\(tableId, picked\.common_ids, config, indices\)/);
});
