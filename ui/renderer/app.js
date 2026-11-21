const api = window.aibcr;
const $ = (selector) => document.querySelector(selector);
const profileSelect = $('#site-select');
const profileCount = $('#profile-count');
const profileList = $('#profile-list');
const runButton = $('#run-profiles');
const notice = $('#notice');
const statusByIndex = new Map();
const profileStateByIndex = new Map();
let proxyItems = [];
let proxyAssignments = {};
let lastSiteLabel = 'Chưa chạy';

window.addEventListener('error', (event) => showNotice(String(event.message || event.error), true));
window.addEventListener('unhandledrejection', (event) => showNotice(String(event.reason), true));

function showNotice(message, isError = false) {
  notice.textContent = message;
  notice.dataset.state = isError ? 'error' : 'ready';
}

function profileIndex(game) {
  if (game === 'baccarat') return 1;
  const match = /^baccarat-profile-(\d+)$/.exec(game || '');
  return match ? Number(match[1]) : 0;
}

function updateProfile(index, state, detail = '') {
  const row = statusByIndex.get(index);
  profileStateByIndex.set(index, state);
  if (!row) {
    $('#close-profiles').disabled = !Array.from(profileStateByIndex.values())
      .some((item) => item === 'running' || item === 'opening' || item === 'closing');
    return;
  }
  row.className = `profile-row ${state}`;
  row.querySelector('.profile-state').textContent = state === 'running' ? 'Đang chạy'
    : state === 'opening' ? 'Đang mở' : state === 'closing' ? 'Đang đóng'
      : state === 'error' ? 'Có lỗi' : 'Đã đóng';
  row.querySelector('.profile-detail').textContent = detail;
  const button = row.querySelector('.profile-toggle');
  if (button) {
    button.textContent = state === 'running' || state === 'opening' ? 'Đóng' : 'Mở';
    button.disabled = state === 'opening' || state === 'closing';
  }
  $('#close-profiles').disabled = !Array.from(profileStateByIndex.values())
    .some((item) => item === 'running' || item === 'opening' || item === 'closing');
}

function renderProfiles(count, siteLabel, replies = []) {
  profileList.replaceChildren();
  statusByIndex.clear();
  lastSiteLabel = siteLabel || lastSiteLabel;
  $('#profile-total').textContent = `${count} profile · ${lastSiteLabel}`;
  $('#header-profile-count').textContent = String(count);
  for (let index = 1; index <= count; index += 1) {
    const reply = replies[index - 1] || {};
    const state = reply.ok ? 'opening' : reply.error ? 'error' : (profileStateByIndex.get(index) || 'closed');
    const row = document.createElement('article');
    row.className = `profile-row ${state}`;
    row.innerHTML = `<div class="profile-number">${String(index).padStart(2, '0')}</div>
      <div class="profile-info"><strong>Profile ${index}</strong><span class="profile-detail"></span></div>
      <span class="profile-state"></span><button class="profile-toggle" data-profile="${index}">Mở</button>`;
    const detail = reply.note || reply.error || '';
    const proxy = reply.proxy ? ` · ${reply.proxy}` : '';
    const size = reply.width && reply.height ? ` · ${reply.width}×${reply.height} · ${reply.scale}%` : '';
    row.querySelector('.profile-detail').textContent = `${detail}${proxy}${size}`;
    row.querySelector('.profile-state').textContent = state === 'running' ? 'Đang chạy'
      : state === 'opening' ? 'Đang mở' : state === 'error' ? 'Có lỗi' : 'Đã đóng';
    profileList.append(row);
    statusByIndex.set(index, row);
    profileStateByIndex.set(index, state);
    updateProfile(index, state, row.querySelector('.profile-detail').textContent);
  }
}

function updateSitePreview() {
  const site = profileSelect.selectedOptions[0];
  runButton.disabled = !site || !site.value;
  $('#run-site-stat').textContent = site && site.value ? site.textContent : 'Ch\u01b0a ch\u1ecdn';
  $('#run-mode-title').textContent = site && site.value === 'febet' ? 'T\u1ef1 ch\u1ecdn b\u00e0n Dream Gaming' : 'M\u1edf \u0111\u1ed3ng th\u1eddi c\u00e1c profile';
  $('#run-mode-badge').textContent = site && site.value === 'febet' ? 'T\u1ef0 \u0110\u1ed8NG' : 'S\u1eb4N S\u00c0NG';
}

function populateProxySelect(select, selectedId = '') {
  select.replaceChildren();
  const direct = document.createElement('option');
  direct.value = '';
  direct.textContent = 'Không dùng proxy';
  select.append(direct);
  for (const proxy of proxyItems) {
    const option = document.createElement('option');
    option.value = proxy.id;
    option.textContent = `${proxy.label}${proxy.status === 'live' ? ' · Còn sống' : proxy.status === 'dead' ? ' · Lỗi' : ''}`;
    select.append(option);
  }
  select.value = proxyItems.some((proxy) => proxy.id === selectedId) ? selectedId : '';
}

const SHARED_WINDOW_KEY = 'aibcr.sharedWindowSettings';
const sharedWindowInputs = {
  width: $('#shared-window-width'),
  height: $('#shared-window-height'),
  scale: $('#shared-window-scale'),
};
const SHARED_WINDOW_DEFAULTS = { width: 900, height: 1200, scale: 60 };

function readSharedWindowSettings() {
  const limits = { width: [520, 3840], height: [200, 2160], scale: [50, 200] };
  return Object.fromEntries(Object.entries(sharedWindowInputs).map(([key, input]) => {
    const value = Number(input.value);
    const [min, max] = limits[key];
    return [key, Number.isFinite(value) && value >= min && value <= max
      ? Math.round(value) : SHARED_WINDOW_DEFAULTS[key]];
  }));
}

function saveSharedWindowSettings() {
  const settings = readSharedWindowSettings();
  for (const [key, input] of Object.entries(sharedWindowInputs)) input.value = settings[key];
  localStorage.setItem(SHARED_WINDOW_KEY, JSON.stringify(settings));
}

function restoreSharedWindowSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(SHARED_WINDOW_KEY) || '{}');
    for (const [key, input] of Object.entries(sharedWindowInputs)) {
      const value = Number(saved[key]);
      const [min, max] = key === 'width' ? [520, 3840]
        : key === 'height' ? [200, 2160] : [50, 200];
      input.value = Number.isFinite(value) && value >= min && value <= max
        ? Math.round(value) : SHARED_WINDOW_DEFAULTS[key];
    }
  } catch {
    for (const [key, input] of Object.entries(sharedWindowInputs)) {
      input.value = SHARED_WINDOW_DEFAULTS[key];
    }
  }
}

function collectSettings(count) {
  const shared = readSharedWindowSettings();
  return Array.from({ length: count }, (_, offset) => ({
    ...shared,
    proxyId: proxyAssignments[String(offset + 1)] || '',
  }));
}

for (const input of Object.values(sharedWindowInputs)) {
  input.addEventListener('change', saveSharedWindowSettings);
}
restoreSharedWindowSettings();

function renderProxyList() {
  const list = $('#proxy-list');
  list.replaceChildren();
  $('#proxy-total').textContent = `${proxyItems.length} proxy`;
  $('#proxy-empty').hidden = proxyItems.length > 0;
  for (const proxy of proxyItems) {
    const row = document.createElement('tr');
    row.innerHTML = '<td class="proxy-label"></td><td><span class="proxy-status"></span><small class="proxy-message"></small></td><td><button class="proxy-remove" type="button">Xóa</button></td>';
    row.querySelector('.proxy-label').textContent = proxy.label;
    const status = row.querySelector('.proxy-status');
    status.textContent = proxy.status === 'live' ? 'Còn sống'
      : proxy.status === 'dead' ? 'Không kết nối' : 'Chưa kiểm tra';
    status.dataset.state = proxy.status;
    row.querySelector('.proxy-message').textContent = proxy.message || '';
    row.querySelector('.proxy-remove').dataset.proxyId = proxy.id;
    list.append(row);
  }
  renderProxyAssignments(Math.max(1, Math.min(8, Number(profileCount.value) || 1)));
}

function setProxyState(result) {
  proxyItems = result.items || [];
  proxyAssignments = result.assignments || proxyAssignments;
  renderProxyList();
}

function renderProxyAssignments(count) {
  const list = $('#proxy-assignments');
  if (!list) return;
  list.replaceChildren();
  for (let index = 1; index <= count; index += 1) {
    const row = document.createElement('label');
    row.className = 'proxy-assignment-row';
    row.innerHTML = '<span></span><select></select>';
    row.querySelector('span').textContent = `Profile ${index}`;
    const select = row.querySelector('select');
    select.dataset.profile = String(index);
    populateProxySelect(select, proxyAssignments[String(index)] || '');
    list.append(row);
  }
}

profileSelect.addEventListener('change', updateSitePreview);
profileCount.addEventListener('input', () => {
  const value = Math.max(1, Math.min(8, Math.trunc(Number(profileCount.value) || 1)));
  $('#run-count-stat').textContent = String(value);
  $('#header-profile-count').textContent = String(value);
});
document.querySelectorAll('[data-tab-target]').forEach((button) => {
  button.addEventListener('click', () => {
    const target = button.dataset.tabTarget;
    document.querySelectorAll('[data-tab-target]').forEach((item) => {
      const active = item === button;
      item.classList.toggle('active', active);
      item.setAttribute('aria-selected', String(active));
    });
    document.querySelectorAll('[data-tab-panel]').forEach((panel) => {
      panel.classList.toggle('active', panel.dataset.tabPanel === target);
    });
  });
});
$('#profile-count').addEventListener('change', () => {
  const value = Math.max(1, Math.min(8, Number(profileCount.value) || 1));
  profileCount.value = String(value);
  renderProxyAssignments(value);
  renderProfiles(value, lastSiteLabel);
});

$('#proxy-assignments').addEventListener('change', async (event) => {
  const select = event.target.closest('select[data-profile]');
  if (!select) return;
  const index = Number(select.dataset.profile);
  const result = await api.assignProxy(index, select.value || null);
  if (!result || !result.ok) {
    $('#proxy-notice').textContent = (result && result.error) || 'Không lưu được proxy cho profile.';
    return;
  }
  proxyAssignments = result.assignments || {};
  $('#proxy-notice').textContent = select.value
    ? `Đã gán proxy cho Profile ${index}; áp dụng khi mở profile.`
    : `Đã bỏ proxy ở Profile ${index}.`;
});

$('#proxy-choose-file').addEventListener('click', () => $('#proxy-file').click());
$('#proxy-file').addEventListener('change', async (event) => {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  try { $('#proxy-import-text').value = await file.text(); }
  catch (error) { $('#proxy-notice').textContent = `Không đọc được file: ${error.message || error}`; }
  event.target.value = '';
});

$('#proxy-import').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  const text = $('#proxy-import-text').value;
  if (!text.trim()) {
    $('#proxy-notice').textContent = 'Nhập danh sách proxy hoặc chọn file trước.';
    return;
  }
  button.disabled = true;
  try {
    const result = await api.importProxyText(text);
    setProxyState(result);
    $('#proxy-import-text').value = '';
    const invalid = result.invalid || [];
    $('#proxy-notice').textContent = `Đã thêm ${result.added}, trùng ${result.duplicate}${invalid.length ? `, sai định dạng ${invalid.length} dòng` : ''}.`;
  } catch (error) {
    $('#proxy-notice').textContent = String(error.message || error);
  } finally {
    button.disabled = false;
  }
});

$('#proxy-check').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  if (!proxyItems.length) {
    $('#proxy-notice').textContent = 'Chưa có proxy để kiểm tra.';
    return;
  }
  button.disabled = true;
  button.textContent = 'Đang kiểm tra…';
  $('#proxy-notice').textContent = 'Đang kiểm tra kết nối HTTPS qua các proxy…';
  try {
    const result = await api.checkProxies();
    setProxyState(result);
    $('#proxy-notice').textContent = `Còn sống: ${result.live} · Không kết nối: ${result.dead}.`;
  } catch (error) {
    $('#proxy-notice').textContent = String(error.message || error);
  } finally {
    button.disabled = false;
    button.textContent = 'Test proxy';
  }
});

$('#proxy-list').addEventListener('click', async (event) => {
  const button = event.target.closest('.proxy-remove');
  if (!button) return;
  button.disabled = true;
  try {
    setProxyState(await api.removeProxy(button.dataset.proxyId));
    $('#proxy-notice').textContent = 'Đã xóa proxy.';
  } catch (error) {
    $('#proxy-notice').textContent = String(error.message || error);
  }
});

runButton.addEventListener('click', async () => {
  const count = Math.max(1, Math.min(8, Math.trunc(Number(profileCount.value) || 1)));
  profileCount.value = String(count);
  $('#run-count-stat').textContent = String(count);
  $('#run-table-stat').textContent = profileSelect.value === 'febet' ? '\u0110ang qu\u00e9t...' : '\u2014';
  runButton.disabled = true;
  runButton.classList.add('busy');
  showNotice('Đang khởi chạy các profile…');
  try {
    const result = await api.openProfiles(count, profileSelect.value, collectSettings(count));
    if (!result || !result.ok) {
      showNotice((result && result.error) || 'Không mở được các profile.', true);
      return;
    }
    renderProfiles(result.count, result.site, result.replies);
    $('#close-profiles').disabled = false;
    const failed = result.replies.filter((reply) => !reply.ok).length;
    if (profileSelect.value === 'febet') {
      showNotice('\u0110ang m\u1edf s\u1ea3nh Dream Gaming tr\u00ean t\u1ea5t c\u1ea3 profile...');
      const dgResult = await api.openDreamGaming();
      if (!dgResult || !dgResult.ok) {
        showNotice((dgResult && dgResult.error) || 'Kh\u00f4ng m\u1edf \u0111\u01b0\u1ee3c s\u1ea3nh Dream Gaming.', true);
        return;
      }
      const dgFailed = dgResult.replies.filter((reply) => !reply.ok).length;
      if (dgFailed) {
        showNotice(`\u0110\u00e3 m\u1edf ${result.count} profile; ${dgFailed} profile ch\u01b0a t\u1ea3i \u0111\u01b0\u1ee3c s\u1ea3nh DG.`, true);
        return;
      }
      showNotice('\u0110ang \u0111\u1ee3i Laya t\u1ea3i b\u00e0n, t\u1ef1 ch\u1ecdn b\u00e0n v\u00e0 \u0111\u1ed3ng b\u1ed9 c\u1ea3 nh\u00f3m...');
      const started = await api.autoRunFebet();
      if (!started || !started.ok) {
        showNotice((started && started.error) || 'Ch\u01b0a th\u1ec3 \u0111\u1ed3ng b\u1ed9 nh\u00f3m v\u00e0o b\u00e0n DG.', true);
        return;
      }
      $('#run-table-stat').textContent = `${started.table_name} \u00b7 ${started.table_id}`;
      renderBetAssignments(started);
      showNotice(`C\u1ea3 ${started.count} profile \u0111\u00e3 v\u00e0o ${started.table_name} (${started.table_id}); \u0111ang ch\u1edd tr\u1ea1ng th\u00e1i c\u01b0\u1ee3c \u0111\u1ed3ng b\u1ed9.`);
    } else {
      showNotice(failed
        ? `Đã gửi lệnh mở ${result.count} profile; ${failed} profile báo lỗi.`
        : `Đã gửi lệnh mở đồng thời ${result.count} profile tại ${result.site}.`);
    }
  } catch (error) {
    showNotice(String(error.message || error), true);
  } finally {
    runButton.classList.remove('busy');
    runButton.disabled = !profileSelect.value;
  }
});

$('#close-profiles').addEventListener('click', async () => {
  const button = $('#close-profiles');
  button.disabled = true;
  try {
    const result = await api.closeProfiles();
    if (!result || !result.ok) {
      showNotice((result && result.error) || 'Không đóng được các profile.', true);
      return;
    }
    for (const index of profileStateByIndex.keys()) updateProfile(index, 'closed', 'Đã đóng Chrome profile.');
    showNotice(`Đã gửi lệnh đóng ${result.count} cửa sổ Chrome.`);
  } catch (error) {
    showNotice(String(error.message || error), true);
  }
});

profileList.addEventListener('click', async (event) => {
  const button = event.target.closest('.profile-toggle');
  if (!button) return;
  const index = Number(button.dataset.profile);
  const state = profileStateByIndex.get(index);
  const closing = state === 'running' || state === 'opening';
  button.disabled = true;
  updateProfile(index, closing ? 'closing' : 'opening', closing ? 'Đang đóng Chrome…' : 'Đang mở Chrome…');
  try {
    const result = closing
      ? await api.closeProfile(index)
      : await api.openProfile(index, Math.max(1, Math.min(8, Number(profileCount.value) || index)),
        collectSettings(Math.max(1, Math.min(8, Number(profileCount.value) || index)))[index - 1],
        profileSelect.selectedOptions[0] && profileSelect.selectedOptions[0].dataset.url);
    if (!result || !result.ok) {
      updateProfile(index, 'error', (result && result.error) || 'Không thực hiện được thao tác.');
      return;
    }
    if (closing) {
      updateProfile(index, 'closed', result.note || 'Đã đóng Chrome profile.');
      showNotice(`Đã đóng Profile ${index}.`);
    } else {
      const dims = result.width && result.height ? ` · ${result.width}×${result.height} · ${result.scale}%` : '';
      updateProfile(index, 'opening', `${result.note || 'Đang mở Chrome.'} · ${result.proxy || 'IP trực tiếp'}${dims}`);
      showNotice(`Đang mở riêng Profile ${index} trong Chrome.`);
    }
  } catch (error) {
    updateProfile(index, 'error', String(error.message || error));
  }
});

const LADDER_PRESETS = {
  '3tk': '260 280 300 240 220 280 320 340 380 400 360 420 440 480 500 420 340 380 440 280 400 360 300 340 280 400 360 300 280',
  '45tk': '500 600 620 540 680 540 580 640 500 480 600 580 700 680 640 520 480 500 600 620 540 680 540 620 540 680 540 580',
  '67tk': '600 640 700 620 720 680 760 660 800 580 620 660 600 620 720 800 740 640 620 580 700 640 800',
  basic: '200 300 240 220 280 320 340 380 400 360 420 440 480 500',
};

function readBetConfig() {
  const stakes = $('#bet-ladder-stakes').value.trim().split(/[\s,-]+/)
    .map((value) => Math.trunc(Number(value))).filter((value) => Number.isInteger(value) && value > 0);
  return {
    stakes,
    min_t: Number($('#bet-min-stake').value),
    max_t: Number($('#bet-max-stake').value),
    min_tk: Number($('#bet-min-profiles').value),
    total_bet: Number($('#bet-total-target').value),
    hop_min: $('#bet-hop-rounds').value.trim(),
    hop_max: Number($('#bet-hop-limit').value),
    split: $('#bet-split').value,
    auto_confirm: $('#bet-auto-confirm').checked,
  };
}

function updateBetPreview() {
  const config = readBetConfig();
  const first = config.stakes[0] || config.min_t || 0;
  const initial = Math.max(config.min_t || 1, Math.min(config.max_t || first, first));
  $('#bet-stake-preview').textContent = config.stakes.length
    ? `Dãy ${config.stakes.length} mức · mức đầu ${initial.toLocaleString('vi-VN')}k · thắng về mức đầu, thua tiến một mức, hòa giữ nguyên.`
    : 'Nhập ít nhất một mức cược hợp lệ.';
}

function fillBetConfig(config) {
  $('#bet-ladder-stakes').value = (config.stakes || []).join(' ');
  $('#bet-min-stake').value = config.min_t ?? 20;
  $('#bet-max-stake').value = config.max_t ?? 10000;
  $('#bet-min-profiles').value = config.min_tk ?? 3;
  $('#bet-total-target').value = config.total_bet ?? 5000;
  $('#bet-hop-rounds').value = config.hop_min ?? '2';
  $('#bet-hop-limit').value = config.hop_max ?? 5;
  $('#bet-split').value = config.split === 'odd-b' ? 'odd-b' : 'odd-p';
  $('#bet-auto-confirm').checked = config.auto_confirm === true;
  const match = Object.entries(LADDER_PRESETS).find(([, sequence]) =>
    sequence === $('#bet-ladder-stakes').value);
  $('#bet-ladder-preset').value = match ? match[0] : 'custom';
  updateBetPreview();
}

$('#bet-ladder-preset').addEventListener('change', (event) => {
  const preset = LADDER_PRESETS[event.currentTarget.value];
  if (preset) $('#bet-ladder-stakes').value = preset;
  updateBetPreview();
});
$('#bet-ladder-stakes').addEventListener('input', () => {
  $('#bet-ladder-preset').value = 'custom';
  updateBetPreview();
});
document.querySelectorAll('#bet-min-stake, #bet-max-stake, #bet-min-profiles, #bet-total-target, #bet-hop-rounds, #bet-hop-limit, #bet-split')
  .forEach((input) => input.addEventListener('input', updateBetPreview));
$('#bet-auto-confirm').addEventListener('change', updateBetPreview);
$('#save-bet-config').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  $('#bet-notice').textContent = 'Đang lưu và áp dụng dãy cược…';
  try {
    const result = await api.saveBetConfig(readBetConfig());
    $('#bet-notice').textContent = result.note || (result.ok ? 'Đã lưu cấu hình.' : result.error);
    $('#bet-notice').dataset.state = result.ok ? 'ready' : 'error';
  } catch (error) {
    $('#bet-notice').textContent = String(error.message || error);
    $('#bet-notice').dataset.state = 'error';
  } finally {
    button.disabled = false;
  }
});
updateBetPreview();

api.onGroupHop((status) => {
  const target = $('#bet-notice');
  if (!target || !status || !status.note) return;
  target.textContent = status.note;
  if (status.table_id) $('#run-table-stat').textContent = status.table_id;
  target.dataset.state = status.error ? 'error' : 'ready';
  showNotice(status.note, Boolean(status.error));
});

function renderBetAssignments(result) {
  const list = $('#bet-assignments');
  list.replaceChildren();
  if (!result || !result.ok) {
    $('#bet-notice').textContent = (result && result.error) || 'Không áp dụng được cấu hình cược.';
    return;
  }
  const failed = [];
  for (const reply of result.replies || []) {
    const row = document.createElement('div');
    row.className = 'proxy-assignment';
    row.textContent = reply.ok
      ? `Profile ${reply.index}: cửa ${reply.side} · ${Number(reply.stake).toLocaleString('vi-VN')} đv mỗi tay`
      : `Profile ${reply.index}: lỗi — ${reply.error}`;
    list.append(row);
    if (!reply.ok) failed.push(reply.index);
  }
  $('#bet-notice').textContent = failed.length
    ? `Đã áp dụng ${result.count - failed.length}/${result.count} profile; lỗi: ${failed.join(', ')}.`
    : `Đã áp dụng cho ${result.count} profile: cùng ${Number(result.stake).toLocaleString('vi-VN')} đv/tay, hai cửa đối lập.`;
}

document.querySelectorAll('[data-win]').forEach((button) => {
  button.addEventListener('click', () => api.windowControl(button.dataset.win));
});

api.onEngineEvent(({ game, event, data }) => {
  const index = profileIndex(game);
  if (!index || !statusByIndex.has(index)) return;
  if (event === 'opened') updateProfile(index, 'running', String(data || 'Chrome đã mở.'));
  else if (event === 'open_error') updateProfile(index, 'error', String(data || 'Không mở được Chrome.'));
  else if (event === 'stopped') updateProfile(index, 'closed', String(data || 'Đã đóng profile.'));
  else if (event === 'state' && data && data.chrome_connected) {
    updateProfile(index, 'running', data.connection_text || 'Chrome đã kết nối.');
  }
});

(async function boot() {
  try {
    const info = await api.info();
    profileSelect.replaceChildren();
    for (const site of info.profileSites || []) {
      const option = document.createElement('option');
      option.value = site.id;
      option.textContent = site.label;
      option.dataset.url = site.url;
      profileSelect.append(option);
    }
    profileSelect.disabled = false;
    const betConfig = await api.getBetConfig();
    if (betConfig && betConfig.ok) fillBetConfig(betConfig.config || {});
    setProxyState(await api.listProxies());
    renderProfiles(Math.max(1, Math.min(8, Number(profileCount.value) || 1)), lastSiteLabel);
    updateSitePreview();
    showNotice('');
  } catch (error) {
    showNotice(`Không tải được danh sách website: ${error.message || error}`, true);
  }
})();
