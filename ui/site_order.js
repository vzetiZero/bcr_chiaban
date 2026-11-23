// Sắp xếp thứ tự site trong danh sách cấu hình.
//
// Thứ tự này không chỉ là hiển thị: nó chính là thứ tự option trong dropdown
// chọn site của từng Profile, và là thứ tự mặc định khi mở/chạy nhóm. Vì vậy
// phần tính toán được tách ra thành hàm thuần để test được mà không cần
// Electron hay đọc/ghi file.
//
// Ba thao tác:
//   "top"  -> đưa site lên vị trí 1
//   "up"   -> tăng 1 vị trí
//   "down" -> giảm 1 vị trí
//
// Site đã ở biên thì trả `moved: false` kèm lời nhắn, không ném lỗi: bấm nút bị
// khoá trên UI không phải là lỗi, và API cũng không nên biến nó thành lỗi.

const SITE_ORDER_ACTIONS = Object.freeze(['top', 'up', 'down']);

function normalizeSiteOrderId(value) {
  return String(value == null ? '' : value).trim().toLowerCase();
}

/**
 * Tính danh sách site mới sau khi sắp xếp.
 *
 * @param {Array<{id: string, label?: string}>} sites danh sách hiện tại
 * @param {string} id mã site cần di chuyển
 * @param {'top'|'up'|'down'} action thao tác
 * @returns {{ok: true, sites: Array, moved: boolean, note: string}
 *          | {ok: false, error: string}}
 */
function reorderSites(sites, id, action) {
  const list = Array.isArray(sites) ? sites : [];
  const target = normalizeSiteOrderId(id);
  const index = list.findIndex((site) => normalizeSiteOrderId(site?.id) === target);
  if (index < 0) return { ok: false, error: 'Không tìm thấy site cần sắp xếp.' };

  const step = String(action == null ? '' : action).trim().toLowerCase();
  if (!SITE_ORDER_ACTIONS.includes(step)) {
    return { ok: false, error: 'Thao tác sắp xếp không hợp lệ.' };
  }

  const label = list[index].label || list[index].id || target;
  if (step === 'top' && index === 0) {
    return { ok: true, sites: list.slice(), moved: false,
      note: `${label} đã ở vị trí 1.` };
  }
  if (step === 'up' && index === 0) {
    return { ok: true, sites: list.slice(), moved: false,
      note: `${label} đã ở đầu danh sách.` };
  }
  if (step === 'down' && index === list.length - 1) {
    return { ok: true, sites: list.slice(), moved: false,
      note: `${label} đã ở cuối danh sách.` };
  }

  const updated = list.slice();
  const [moved] = updated.splice(index, 1);
  const destination = step === 'top' ? 0 : step === 'up' ? index - 1 : index + 1;
  updated.splice(destination, 0, moved);
  const note = step === 'down'
    ? `Đã đưa ${label} xuống vị trí ${destination + 1}.`
    : `Đã đưa ${label} lên vị trí ${destination + 1}.`;
  return { ok: true, sites: updated, moved: true, note };
}

module.exports = { reorderSites, SITE_ORDER_ACTIONS, normalizeSiteOrderId };
