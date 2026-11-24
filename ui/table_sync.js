'use strict';

// Chọn bàn DG cho cả nhóm.
//
// Nguyên tắc bắt buộc: mọi profile phải vào **cùng một bàn thật** kể cả khi chúng
// vào từ site khác nhau. Mã bàn 60xxx là không gian chung của DG, nên bàn chỉ hợp
// lệ khi nó xuất hiện trong danh sách của **tất cả** sảnh. Trước đây bàn được lấy
// từ profile dẫn đầu rồi ép các profile còn lại vào, nên hai site có tập bàn khác
// nhau sẽ bị tách bàn mà không ai báo.

const TABLE_ID_RE = /^60\d{3,}$/;

function normalizeTables(rows) {
  const seen = new Map();
  for (const row of rows || []) {
    const id = String(row?.table_id || '').trim();
    if (!TABLE_ID_RE.test(id)) continue;
    const online = Math.max(0, Math.trunc(Number(row?.online) || 0));
    const name = String(row?.name || '').trim();
    const previous = seen.get(id);
    if (previous) {
      // Cùng một bàn có thể được liệt kê hai lần trên một sảnh (Laya vẽ lại);
      // giữ số người lớn nhất và tên đầu tiên đọc được.
      previous.online = Math.max(previous.online, online);
      if (!previous.name && name) previous.name = name;
      continue;
    }
    seen.set(id, { table_id: id, name, online });
  }
  return [...seen.values()];
}

// `perProfile` là mảng (mỗi profile một mảng bàn). Trả về các bàn có mặt ở mọi
// profile, ưu tiên bàn đông người nhất (tổng, rồi tới mức thấp nhất trong nhóm).
function commonTables(perProfile) {
  const lists = (perProfile || []).map(normalizeTables);
  if (!lists.length) return [];
  const merged = new Map();
  for (const rows of lists) {
    for (const row of rows) {
      const entry = merged.get(row.table_id)
        || { table_id: row.table_id, name: '', online: [] };
      entry.online.push(row.online);
      if (!entry.name && row.name) entry.name = row.name;
      merged.set(row.table_id, entry);
    }
  }
  const shared = [];
  for (const entry of merged.values()) {
    if (entry.online.length !== lists.length) continue;
    shared.push({
      table_id: entry.table_id,
      name: entry.name,
      online: Math.min(...entry.online),
      total: entry.online.reduce((sum, value) => sum + value, 0),
    });
  }
  shared.sort((a, b) => (b.total - a.total) || (b.online - a.online)
    || a.table_id.localeCompare(b.table_id, undefined, { numeric: true }));
  return shared;
}

function pickSharedTable(perProfile) {
  const lists = (perProfile || []).map(normalizeTables);
  if (!lists.length) {
    return { ok: false, error: 'Chưa có profile nào để đồng bộ bàn.' };
  }
  const empty = lists
    .map((rows, offset) => ({ index: offset, rows }))
    .filter((item) => !item.rows.length)
    .map((item) => item.index);
  if (empty.length) {
    return {
      ok: false,
      missing: empty,
      per_profile: lists.map((rows) => rows.map((row) => row.table_id)),
      error: `Chưa đọc được danh sách bàn của ${empty.length}/${lists.length} sảnh DG; chưa chọn bàn để tránh tách nhóm.`,
    };
  }
  const shared = commonTables(lists);
  if (!shared.length) {
    return {
      ok: false,
      per_profile: lists.map((rows) => rows.map((row) => row.table_id)),
      error: `Không có bàn DG nào xuất hiện ở cả ${lists.length} sảnh; chưa chuyển bàn để tránh tách nhóm.`,
    };
  }
  const best = shared[0];
  return {
    ok: true,
    table_id: best.table_id,
    table_name: best.name || `Bàn ${best.table_id}`,
    online: best.online,
    // Chỉ xoay trong phần giao: xoay sang bàn mà một sảnh không có sẽ tách nhóm.
    common_ids: shared.map((row) => row.table_id),
    tables: shared,
    per_profile: lists.map((rows) => rows.map((row) => row.table_id)),
  };
}

module.exports = { TABLE_ID_RE, normalizeTables, commonTables, pickSharedTable };
