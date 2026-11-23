// Toast stack — thông báo nổi có animation cho renderer.
//
// Vì CSP của app là `script-src 'self'` (không cho inline script), phần này
// được tách thành tệp riêng và nạp trước app.js. API toàn cục:
//
//   window.aibcrToast.success('Đã lưu cấu hình.');
//   window.aibcrToast.error('Không mở được profile.', { title: 'Lỗi' });
//   window.aibcrToast.show('Đang quét bàn…', { type: 'info', duration: 6000 });
//   window.aibcrToast.dismissAll();
//
// Quy ước: chỉ báo những việc người dùng cần biết. Tiến trình dài dùng
// duration lớn hoặc gọi dismissAll() khi xong.

const TOAST_STACK_ID = 'toast-stack';
const TOAST_MAX_VISIBLE = 4;
const TOAST_DEFAULT_DURATION = 4200;
const TOAST_DEDUPE_MS = 1200;
const TOAST_EXIT_MS = 240;

const TOAST_ICONS = {
  success: '\u2713',
  error: '\u2715',
  warning: '\u0021',
  info: '\u2139',
};

const TOAST_TITLES = {
  success: 'Thành công',
  error: 'Có lỗi',
  warning: 'Cần chú ý',
  info: 'Thông báo',
};

// Chữ ký gần nhất để một lỗi lặp lại vài lần trong cùng một nhịp không làm
// ngập màn hình (ví dụ showNotice bị gọi từ cả engine event và group hop).
const recentToasts = new Map();

function toastStack() {
  let stack = document.getElementById(TOAST_STACK_ID);
  if (stack) return stack;
  stack = document.createElement('div');
  stack.id = TOAST_STACK_ID;
  stack.className = 'toast-stack';
  stack.setAttribute('role', 'region');
  stack.setAttribute('aria-label', 'Thông báo');
  document.body.append(stack);
  return stack;
}

function removeToast(node) {
  if (!node || node.dataset.leaving === '1') return;
  node.dataset.leaving = '1';
  node.classList.add('toast-leaving');
  window.setTimeout(() => node.remove(), TOAST_EXIT_MS);
}

function trimToasts(stack) {
  const live = [...stack.querySelectorAll('.toast:not(.toast-leaving)')];
  while (live.length > TOAST_MAX_VISIBLE) {
    removeToast(live.shift());
  }
}

function toastType(type) {
  return Object.prototype.hasOwnProperty.call(TOAST_ICONS, type) ? type : 'info';
}

function pushToast(message, options = {}) {
  const text = String(message == null ? '' : message).trim();
  if (!text) return null;

  const type = toastType(options.type);
  const now = Date.now();
  const signature = `${type}:${text}`;
  const lastSeen = recentToasts.get(signature) || 0;
  if (now - lastSeen < TOAST_DEDUPE_MS) return null;
  recentToasts.set(signature, now);

  const duration = Number.isFinite(options.duration)
    ? Math.max(1200, Math.min(20000, options.duration))
    : TOAST_DEFAULT_DURATION;

  const stack = toastStack();
  const node = document.createElement('div');
  node.className = `toast toast-${type}`;
  node.setAttribute('role', type === 'error' ? 'alert' : 'status');

  const icon = document.createElement('span');
  icon.className = 'toast-icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.textContent = TOAST_ICONS[type];

  const body = document.createElement('div');
  body.className = 'toast-body';
  const title = document.createElement('strong');
  title.className = 'toast-title';
  title.textContent = String(options.title || TOAST_TITLES[type]);
  const line = document.createElement('span');
  line.className = 'toast-message';
  line.textContent = text;
  body.append(title, line);

  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'toast-close';
  close.setAttribute('aria-label', 'Đóng thông báo');
  close.textContent = '\u00d7';
  close.addEventListener('click', () => {
    window.clearTimeout(node._toastTimer);
    removeToast(node);
  });

  const progress = document.createElement('span');
  progress.className = 'toast-progress';
  progress.setAttribute('aria-hidden', 'true');
  progress.style.animationDuration = `${duration}ms`;

  node.append(icon, body, close, progress);
  stack.append(node);
  trimToasts(stack);

  // Tạm dừng đếm giờ khi rê chuột để người dùng kịp đọc.
  let remaining = duration;
  let startedAt = Date.now();
  const arm = () => {
    startedAt = Date.now();
    node._toastTimer = window.setTimeout(() => removeToast(node), remaining);
  };
  const disarm = () => {
    window.clearTimeout(node._toastTimer);
    remaining = Math.max(600, remaining - (Date.now() - startedAt));
  };
  node.addEventListener('mouseenter', () => {
    disarm();
    node.classList.add('toast-paused');
  });
  node.addEventListener('mouseleave', () => {
    node.classList.remove('toast-paused');
    arm();
  });
  arm();

  return node;
}

window.aibcrToast = {
  show: pushToast,
  success: (message, options = {}) => pushToast(message, { ...options, type: 'success' }),
  error: (message, options = {}) => pushToast(message, { ...options, type: 'error' }),
  warning: (message, options = {}) => pushToast(message, { ...options, type: 'warning' }),
  info: (message, options = {}) => pushToast(message, { ...options, type: 'info' }),
  dismissAll: () => {
    const stack = document.getElementById(TOAST_STACK_ID);
    if (!stack) return;
    stack.querySelectorAll('.toast').forEach(removeToast);
  },
};
