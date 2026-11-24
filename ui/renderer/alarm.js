// Còi báo động sự cố (port từ logic Bacabot/New folder).
//
// Còi hú bằng Web Audio API khi có sự cố nghiêm trọng: lệch tiền, đặt sai số
// tiền, casino từ chối chip, lệch bàn/không tìm thấy bàn, dừng cược an toàn.
// Toàn bộ âm thanh được tổng hợp bằng oscillator nên không cần tệp âm thanh nào.

const ALARM_STORAGE_KEY = 'aibcr.alarm.enabled';
const ALARM_VOLUME_KEY = 'aibcr.alarm.volume';
const ALARM_THROTTLE_MS = 2500;

// Chỉ những sự cố tài chính/an toàn mới hú còi. Thông báo tiến trình thường
// (đang chờ ván, đã vào bàn, bỏ qua tay) không được kích hoạt.
const ALARM_PATTERNS = [
  'lệch tiền',
  'chênh lệch',
  'cược sai số tiền',
  'lỗi đặt chip',
  'từ chối nhận chip',
  'vượt quá giới hạn',
  'khác bàn',
  'lệch bàn',
  'không tìm thấy bàn',
  'chưa nhận bàn',
  'không đồng bộ',
  'dừng cược',
  'chặn cược',
  'chặn đứng cược lệch',
  'hủy sạch chip',
  'hủy lệnh an toàn',
  'fail-safe rollback',
  'bảo toàn vốn',
  'tự động ngắt tk',
  'không xếp đủ chip',
  'dừng hẳn',
  // Cần người thật thao tác ngay trên Chrome: sảnh DG chặn bằng captcha thanh
  // trượt. Tool **không bao giờ tự giải**; nó chỉ hú còi để người dùng kéo tay.
  // Bản Laya mới (đo trên 888AE66) vẽ captcha bằng tiếng Anh.
  'xác minh an toàn',
  'kéo thanh trượt',
  'drag the slider',
  'safetyverify',
];

let alarmContext = null;
let alarmEnabled = true;
let alarmVolume = 0.8;
let lastAlarmAt = 0;

function normalizeForAlarm(text) {
  return String(text || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[đĐ]/g, 'd')
    .toLowerCase();
}

function loadAlarmSettings() {
  try {
    const savedEnabled = localStorage.getItem(ALARM_STORAGE_KEY);
    if (savedEnabled !== null) alarmEnabled = savedEnabled === 'true';
    const rawVolume = localStorage.getItem(ALARM_VOLUME_KEY);
    if (rawVolume !== null && rawVolume.trim() !== '') {
      const savedVolume = Number(rawVolume);
      if (Number.isFinite(savedVolume) && savedVolume >= 0 && savedVolume <= 1) {
        alarmVolume = savedVolume;
      }
    }
  } catch (error) {
    // localStorage có thể bị chặn; giữ mặc định.
  }
}

function ensureAlarmContext() {
  if (!alarmContext) {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (Ctor) alarmContext = new Ctor();
  }
  if (alarmContext && alarmContext.state === 'suspended') {
    alarmContext.resume().catch(() => {});
  }
  return alarmContext;
}

function alarmVolumePercent() {
  return Math.round(alarmVolume * 100);
}

function syncAlarmUI() {
  const toggle = document.getElementById('alarm-toggle');
  const icon = document.getElementById('alarm-sound-icon');
  const stateText = document.getElementById('alarm-state-text');
  const volume = document.getElementById('alarm-volume');
  const volumeText = document.getElementById('alarm-volume-text');
  const box = document.getElementById('alarm-sound-box');

  if (toggle) toggle.setAttribute('aria-pressed', String(alarmEnabled));
  if (icon) icon.textContent = alarmEnabled ? (alarmVolume > 0 ? '\uD83D\uDD0A' : '\uD83D\uDD08') : '\uD83D\uDD07';
  if (stateText) stateText.textContent = alarmEnabled ? 'BẬT' : 'TẮT';
  if (volume) volume.value = String(alarmVolumePercent());
  if (volumeText) volumeText.textContent = `${alarmVolumePercent()}%`;
  if (box) box.classList.toggle('off', !alarmEnabled);
  if (toggle) toggle.title = alarmEnabled ? 'Tắt còi báo động sự cố' : 'Bật còi báo động sự cố';
}

function setAlarmEnabled(enabled) {
  alarmEnabled = Boolean(enabled);
  try { localStorage.setItem(ALARM_STORAGE_KEY, String(alarmEnabled)); } catch (error) {}
  syncAlarmUI();
}

function setAlarmVolume(percent) {
  const value = Math.max(0, Math.min(100, Math.trunc(Number(percent) || 0)));
  alarmVolume = value / 100;
  try { localStorage.setItem(ALARM_VOLUME_KEY, String(alarmVolume)); } catch (error) {}
  syncAlarmUI();
}

function flashAlarmBox() {
  const box = document.getElementById('alarm-sound-box');
  if (!box) return;
  let count = 0;
  const timer = setInterval(() => {
    count += 1;
    box.classList.toggle('flashing', count % 2 === 1);
    if (count >= 8) {
      clearInterval(timer);
      box.classList.remove('flashing');
    }
  }, 250);
}

// Còi hú khẩn cấp: 3 xung ngắn 850→1250Hz rồi 1 xung dài 1300→850Hz.
function playAlarmSiren(durationMs = 2400) {
  if (!alarmEnabled || alarmVolume <= 0) return false;
  const context = ensureAlarmContext();
  if (!context) return false;
  try {
    const now = context.currentTime;
    const master = context.createGain();
    master.gain.setValueAtTime(alarmVolume, now);
    master.connect(context.destination);

    const pulses = [
      { start: 0, duration: 0.30, from: 850, to: 1250 },
      { start: 0.40, duration: 0.30, from: 850, to: 1250 },
      { start: 0.80, duration: 0.30, from: 850, to: 1250 },
      { start: 1.20, duration: 0.80, from: 1300, to: 850 },
    ];
    for (const pulse of pulses) {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = 'sawtooth';
      const startAt = now + pulse.start;
      const endAt = startAt + pulse.duration;
      oscillator.frequency.setValueAtTime(pulse.from, startAt);
      oscillator.frequency.exponentialRampToValueAtTime(pulse.to, endAt);
      gain.gain.setValueAtTime(0, startAt);
      gain.gain.linearRampToValueAtTime(0.85, startAt + 0.04);
      gain.gain.setValueAtTime(0.85, endAt - 0.04);
      gain.gain.linearRampToValueAtTime(0, endAt);
      oscillator.connect(gain);
      gain.connect(master);
      oscillator.start(startAt);
      oscillator.stop(endAt);
    }
    flashAlarmBox();
    return true;
  } catch (error) {
    return false;
  }
}

function testAlarmSound() {
  ensureAlarmContext();
  playAlarmSiren(2000);
}

// Hú còi nếu thông điệp khớp mẫu sự cố; chống hú lặp trong 2.5 giây.
// Patterns are compared diacritic-free, so the stored list is normalised once.
const ALARM_PATTERNS_NORMALIZED = ALARM_PATTERNS.map(normalizeForAlarm);

function alarmForMessage(message, { force = false, level = '' } = {}) {
  // ``action`` = cần người thật thao tác ngay (captcha thanh trượt, đăng nhập).
  // Vẫn phải khớp mẫu sự cố nên thông báo tiến trình thường không hú.
  const actionLevel = String(level || '').toLowerCase() === 'action';
  if (!force && !actionLevel
      && String(level || '').toLowerCase() !== 'error') return false;
  const text = normalizeForAlarm(message);
  if (!force && !ALARM_PATTERNS_NORMALIZED.some((pattern) => text.includes(pattern))) return false;
  const now = Date.now();
  if (now - lastAlarmAt < ALARM_THROTTLE_MS) return false;
  lastAlarmAt = now;
  return playAlarmSiren();
}

function initAlarm() {
  loadAlarmSettings();
  syncAlarmUI();

  const toggle = document.getElementById('alarm-toggle');
  if (toggle) {
    toggle.addEventListener('click', () => {
      setAlarmEnabled(!alarmEnabled);
      if (alarmEnabled) testAlarmSound();
    });
  }
  const volume = document.getElementById('alarm-volume');
  if (volume) volume.addEventListener('input', (event) => setAlarmVolume(event.target.value));
  const test = document.getElementById('alarm-test');
  if (test) test.addEventListener('click', () => testAlarmSound());

  // AudioContext cần một thao tác người dùng trước khi phát được.
  document.addEventListener('click', () => ensureAlarmContext(), { passive: true });
  document.addEventListener('keydown', () => ensureAlarmContext(), { passive: true });
}

window.aibcrAlarm = {
  init: initAlarm,
  notify: alarmForMessage,
  test: testAlarmSound,
  setEnabled: setAlarmEnabled,
  setVolume: setAlarmVolume,
  isEnabled: () => alarmEnabled,
  volumePercent: alarmVolumePercent,
  patterns: ALARM_PATTERNS,
};
