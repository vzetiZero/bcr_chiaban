// Theme sáng/tối — nạp trong <head> để áp màu trước lần vẽ đầu tiên
// (tránh nháy nền tối khi người dùng đang dùng giao diện sáng).
//
// app.js vẫn giữ THEME_KEY + documentElement.dataset.theme cho phần còn lại
// của ứng dụng; ở đây chỉ là bộ điều khiển dùng chung.

const BCR_THEME_KEY = 'aibcr.theme';

function bcrNormalizeTheme(value) {
  return value === 'light' ? 'light' : 'dark';
}

function bcrReadTheme() {
  try {
    return bcrNormalizeTheme(localStorage.getItem(BCR_THEME_KEY));
  } catch {
    return 'dark';
  }
}

function bcrApplyTheme(theme, { persist = true } = {}) {
  const next = bcrNormalizeTheme(theme);
  document.documentElement.dataset.theme = next;
  document.documentElement.style.colorScheme = next;
  if (persist) {
    try { localStorage.setItem(BCR_THEME_KEY, next); } catch { /* chế độ riêng tư */ }
  }
  window.dispatchEvent(new CustomEvent('aibcr:theme-change', { detail: { theme: next } }));
  return next;
}

// Áp ngay lúc parse <head>.
bcrApplyTheme(bcrReadTheme(), { persist: false });

window.aibcrTheme = {
  key: BCR_THEME_KEY,
  current: () => bcrNormalizeTheme(document.documentElement.dataset.theme),
  apply: bcrApplyTheme,
  toggle: () => bcrApplyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'),
};
