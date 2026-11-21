const api = window.aibcr;
const $ = (selector) => document.querySelector(selector);
const profileCount = $('#profile-count');
const profileList = $('#profile-list');
const runButton = $('#run-profiles');
const notice = $('#notice');
const statusByIndex = new Map();
const profileStateByIndex = new Map();
let proxyItems = [];
let proxyAssignments = {};
let omniProfiles = [];
let omniAssignments = {};
let hidemiumProfiles = [];
let hidemiumAssignments = {};
let profileSites = [];
let profileSiteSelections = {};

let activityLogRows = [];

function renderActivityLog() {
  const list = $('#activity-log-list');
  list.replaceChildren();
  $('#activity-log-empty').hidden = activityLogRows.length > 0;
  for (const item of activityLogRows) {
    const row = document.createElement('article');
    row.className = `activity-log-row ${item.level === 'error' ? 'error' : ''}`;
    const meta = document.createElement('div');
    meta.className = 'activity-log-meta';
    const time = document.createElement('time');
    const date = new Date(item.time);
    time.dateTime = Number.isNaN(date.getTime()) ? '' : date.toISOString();
    time.textContent = Number.isNaN(date.getTime()) ? String(item.time || '')
      : date.toLocaleString('vi-VN');
    const source = document.createElement('span');
    source.textContent = String(item.source || 'app');
    meta.append(time, source);
    const text = document.createElement('p');
    text.textContent = String(item.text || '');
    row.append(meta, text);
    list.append(row);
  }
  list.scrollTop = list.scrollHeight;
}

function addActivityLog(item) {
  if (!item || !item.text) return;
  activityLogRows.push(item);
  if (activityLogRows.length > 5000) activityLogRows = activityLogRows.slice(-5000);
  renderActivityLog();
}

api.onActivityLogEntry(addActivityLog);
api.onActivityLogClear(() => {
  activityLogRows = [];
  renderActivityLog();
});

$('#clear-activity-log').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const result = await api.clearActivityLog();
    if (!result?.ok) showNotice('Không xóa được nhật ký.', true);
  } catch (error) {
    showNotice(`Không xóa được nhật ký: ${error.message || error}`, true);
  } finally {
    button.disabled = false;
  }
});
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

function renderProfiles(count, siteLabel, replies = [], indices = null) {
  profileList.replaceChildren();
  statusByIndex.clear();
  lastSiteLabel = siteLabel || 'Site ri\u00eang t\u1eebng profile';
  const order = Array.isArray(indices) && indices.length
    ? indices : Array.from({ length: count }, (_, offset) => offset + 1);
  $('#profile-total').textContent = `${order.length} profile \u00b7 ${lastSiteLabel}`;
  $('#header-profile-count').textContent = String(order.length);
  order.forEach((index, offset) => {
    const reply = replies[offset] || {};
    const state = reply.ok ? 'opening' : reply.error ? 'error' : (profileStateByIndex.get(index) || 'closed');
    const row = document.createElement('article');
    row.className = `profile-row ${state}`;
    row.innerHTML = `<div class="profile-number">${String(index).padStart(2, '0')}</div>
      <div class="profile-info"><strong>Profile ${index}</strong><span class="profile-detail"></span></div>
      <select class="profile-site-select" data-profile="${index}" aria-label="Site c\u1ee7a Profile ${index}"></select>
      <span class="profile-state"></span><button class="profile-toggle" data-profile="${index}">M\u1edf</button>`;
    const siteSelect = row.querySelector('.profile-site-select');
    for (const site of profileSites) {
      const option = document.createElement('option');
      option.value = site.id;
      option.textContent = site.display || site.label;
      siteSelect.append(option);
    }
    const savedSite = profileSiteSelections[String(index)];
    const selectedSite = profileSites.some((site) => site.id === savedSite)
      ? savedSite : profileSites[0]?.id || '';
    if (selectedSite) {
      siteSelect.value = selectedSite;
      profileSiteSelections[String(index)] = selectedSite;
    }
    const detail = reply.note || reply.error || '';
    const proxy = reply.proxy ? ` \u00b7 ${reply.proxy}` : '';
    const size = reply.width && reply.height ? ` \u00b7 ${reply.width}\u00d7${reply.height} \u00b7 ${reply.scale}%` : '';
    row.querySelector('.profile-detail').textContent = `${detail}${proxy}${size}`;
    row.querySelector('.profile-state').textContent = state === 'running' ? '\u0110ang ch\u1ea1y'
      : state === 'opening' ? '\u0110ang m\u1edf' : state === 'error' ? 'C\u00f3 l\u1ed7i' : '\u0110\u00e3 \u0111\u00f3ng';
    profileList.append(row);
    statusByIndex.set(index, row);
    profileStateByIndex.set(index, state);
    updateProfile(index, state, row.querySelector('.profile-detail').textContent);
  });
  localStorage.setItem('aibcr.profileSites', JSON.stringify(profileSiteSelections));
}

function updateSitePreview() {
  const source = $('#profile-source').value;
  runButton.disabled = profileSites.length === 0 || activeProfileSelection().length === 0;
  $('#run-site-stat').textContent = 'Ch\u1ecdn ri\u00eang t\u1eebng profile';
  $('#run-mode-title').textContent = '\u0110\u1ed3ng b\u1ed9 b\u00e0n DG v\u00e0 v\u1eadn h\u00e0nh nh\u00f3m';
  $('#run-mode-badge').textContent = source === 'omni' ? 'OMNILOGIN' : source === 'hidemium' ? 'HIDEMIUM' : 'DG GROUP';
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

function collectSettings(count, indices = null) {
  const shared = readSharedWindowSettings();
  const order = Array.isArray(indices) && indices.length ? indices : null;
  return Array.from({ length: count }, (_, offset) => {
    const profileIndex = order ? order[offset] : offset + 1;
    return {
      ...shared,
      index: profileIndex,
      proxyId: proxyAssignments[String(profileIndex)] || '',
      omniProfileId: omniAssignments[String(profileIndex)] || '',
      hidemiumProfileId: hidemiumAssignments[String(profileIndex)] || '',
    };
  });
}

const PROFILE_SELECTION_KEY = 'aibcr.profileSelection';
let selectedProfileIndices = [];
let profileSelectionTouched = false;

function profileCountValue() {
  return Math.max(1, Math.min(8, Math.trunc(Number(profileCount.value) || 1)));
}

function readStoredSelection() {
  try {
    const parsed = JSON.parse(localStorage.getItem(PROFILE_SELECTION_KEY) || '[]');
    return Array.isArray(parsed)
      ? [...new Set(parsed.map((value) => Math.trunc(Number(value)))
        .filter((value) => Number.isInteger(value) && value >= 1 && value <= 8))].sort((a, b) => a - b)
      : [];
  } catch (error) {
    return [];
  }
}

function activeProfileSelection() {
  const valid = selectedProfileIndices.filter((index) => Number.isInteger(index));
  if (valid.length || profileSelectionTouched) return [...valid].sort((a, b) => a - b);
  return Array.from({ length: profileCountValue() }, (_, offset) => offset + 1);
}

function syncProfilePicker() {
  const host = $('#profile-picker');
  if (!host) return;
  host.replaceChildren();
  const selection = new Set(activeProfileSelection());
  for (let index = 1; index <= 8; index += 1) {
    const label = document.createElement('label');
    label.className = `profile-picker-option${selection.has(index) ? ' checked' : ''}`;
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.value = String(index);
    box.checked = selection.has(index);
    box.dataset.profile = String(index);
    label.append(box, document.createTextNode(`P${index}`));
    host.append(label);
  }
  const hint = document.createElement('span');
  hint.className = 'profile-picker-hint';
  hint.textContent = selection.size
    ? `Đã chọn: ${[...selection].sort((a, b) => a - b).map((index) => `P${index}`).join(', ')}`
    : 'Chưa chọn profile nào.';
  host.append(hint);
  $('#run-count-stat').textContent = String(selection.size || 0);
  if (profileSites.length) runButton.disabled = selection.size === 0;
}

$('#profile-picker').addEventListener('change', (event) => {
  const box = event.target.closest('input[type="checkbox"][data-profile]');
  if (!box) return;
  const index = Math.trunc(Number(box.dataset.profile));
  if (box.checked) {
    if (!selectedProfileIndices.includes(index)) selectedProfileIndices.push(index);
  } else {
    selectedProfileIndices = selectedProfileIndices.filter((value) => value !== index);
  }
  selectedProfileIndices.sort((a, b) => a - b);
  profileSelectionTouched = true;
  localStorage.setItem(PROFILE_SELECTION_KEY, JSON.stringify(selectedProfileIndices));
  syncProfilePicker();
});


const OMNI_API_KEY = 'aibcr.omniApiUrl';
const OMNI_ASSIGNMENTS_KEY = 'aibcr.omniAssignments';
const HIDEMIUM_API_KEY = 'aibcr.hidemiumApiUrl';
const HIDEMIUM_ASSIGNMENTS_KEY = 'aibcr.hidemiumAssignments';
const PROFILE_SOURCE_KEY = 'aibcr.profileSource';

function renderOmniAssignments(count) {
  const list = $('#omni-profile-assignments');
  if (!list) return;
  list.replaceChildren();
  for (let index = 1; index <= count; index += 1) {
    const row = document.createElement('label');
    row.className = 'omni-assignment-row';
    row.innerHTML = '<span></span><select></select>';
    row.querySelector('span').textContent = `Profile ${index}`;
    const select = row.querySelector('select');
    select.dataset.profile = String(index);
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = omniProfiles.length ? 'Ch\u1ecdn profile OmniLogin' : 'K\u1ebft n\u1ed1i API \u0111\u1ec3 t\u1ea3i profiles';
    select.append(empty);
    for (const profile of omniProfiles) {
      const option = document.createElement('option');
      option.value = profile.id;
      option.textContent = `${profile.name} \u00b7 ${profile.id}`;
      select.append(option);
    }
    select.value = omniAssignments[String(index)] || '';
    list.append(row);
  }
}

async function refreshOmniProfiles() {
  const button = $('#omni-refresh');
  button.disabled = true;
  $('#omni-notice').textContent = '\u0110ang k\u1ebft n\u1ed1i API OmniLogin...';
  try {
    const result = await api.listOmniProfiles($('#omni-api-url').value.trim());
    if (!result || !result.ok) throw new Error(result?.error || 'Kh\u00f4ng t\u1ea3i \u0111\u01b0\u1ee3c profiles.');
    omniProfiles = result.profiles || [];
    $('#omni-api-url').value = result.apiUrl;
    localStorage.setItem(OMNI_API_KEY, result.apiUrl);
    omniAssignments = Object.fromEntries(Object.entries(omniAssignments)
      .filter(([, id]) => omniProfiles.some((profile) => profile.id === id)));
    localStorage.setItem(OMNI_ASSIGNMENTS_KEY, JSON.stringify(omniAssignments));
    renderOmniAssignments(Math.max(1, Math.min(8, Number(profileCount.value) || 1)));
    $('#omni-notice').textContent = `OmniLogin k\u1ebft n\u1ed1i th\u00e0nh c\u00f4ng ? ${omniProfiles.length} profiles.`;
  } catch (error) {
    $('#omni-notice').textContent = String(error.message || error);
  } finally {
    button.disabled = false;
  }
}

$('#omni-refresh').addEventListener('click', refreshOmniProfiles);
$('#omni-api-url').addEventListener('change', () => localStorage.setItem(OMNI_API_KEY, $('#omni-api-url').value.trim()));
$('#omni-profile-assignments').addEventListener('change', (event) => {
  const select = event.target.closest('select[data-profile]');
  if (!select) return;
  if (select.value) omniAssignments[select.dataset.profile] = select.value;
  else delete omniAssignments[select.dataset.profile];
  localStorage.setItem(OMNI_ASSIGNMENTS_KEY, JSON.stringify(omniAssignments));
  $('#omni-notice').textContent = `\u0110\u00e3 l\u01b0u g\u00e1n cho Profile ${select.dataset.profile}.`;
});

function renderHidemiumAssignments(count) {
  const list = $('#hidemium-profile-assignments');
  list.replaceChildren();
  for (let index = 1; index <= count; index += 1) {
    const row = document.createElement('label');
    row.className = 'omni-assignment-row';
    row.innerHTML = '<span></span><select></select>';
    row.querySelector('span').textContent = `Profile ${index}`;
    const select = row.querySelector('select');
    select.dataset.profile = String(index);
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = hidemiumProfiles.length ? 'Chọn profile Hidemium' : 'Kết nối API để tải profiles';
    select.append(empty);
    for (const profile of hidemiumProfiles) {
      const option = document.createElement('option');
      option.value = profile.id;
      option.textContent = `${profile.name} · ${profile.id}`;
      select.append(option);
    }
    select.value = hidemiumAssignments[String(index)] || '';
    list.append(row);
  }
}

async function refreshHidemiumProfiles() {
  const button = $('#hidemium-refresh');
  button.disabled = true;
  $('#hidemium-notice').textContent = 'Đang kết nối API Hidemium...';
  try {
    const result = await api.listHidemiumProfiles($('#hidemium-api-url').value.trim());
    if (!result?.ok) throw new Error(result?.error || 'Không tải được profiles.');
    hidemiumProfiles = result.profiles || [];
    $('#hidemium-api-url').value = result.apiUrl;
    localStorage.setItem(HIDEMIUM_API_KEY, result.apiUrl);
    hidemiumAssignments = Object.fromEntries(Object.entries(hidemiumAssignments)
      .filter(([, id]) => hidemiumProfiles.some((profile) => profile.id === id)));
    localStorage.setItem(HIDEMIUM_ASSIGNMENTS_KEY, JSON.stringify(hidemiumAssignments));
    renderHidemiumAssignments(Math.max(1, Math.min(8, Number(profileCount.value) || 1)));
    $('#hidemium-notice').textContent = `Hidemium kết nối thành công · ${hidemiumProfiles.length} profiles.`;
  } catch (error) {
    $('#hidemium-notice').textContent = String(error.message || error);
  } finally {
    button.disabled = false;
  }
}

$('#hidemium-refresh').addEventListener('click', refreshHidemiumProfiles);
$('#hidemium-api-url').addEventListener('change', () => localStorage.setItem(HIDEMIUM_API_KEY, $('#hidemium-api-url').value.trim()));
$('#hidemium-profile-assignments').addEventListener('change', (event) => {
  const select = event.target.closest('select[data-profile]');
  if (!select) return;
  if (select.value) hidemiumAssignments[select.dataset.profile] = select.value;
  else delete hidemiumAssignments[select.dataset.profile];
  localStorage.setItem(HIDEMIUM_ASSIGNMENTS_KEY, JSON.stringify(hidemiumAssignments));
  $('#hidemium-notice').textContent = `Đã lưu gán cho Profile ${select.dataset.profile}.`;
});

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

profileList.addEventListener('change', (event) => {
  const select = event.target.closest('.profile-site-select');
  if (!select) return;
  profileSiteSelections[select.dataset.profile] = select.value;
  localStorage.setItem('aibcr.profileSites', JSON.stringify(profileSiteSelections));
});
$('#profile-source').addEventListener('change', () => {
  localStorage.setItem(PROFILE_SOURCE_KEY, $('#profile-source').value);
  updateSitePreview();
});
profileCount.addEventListener('input', () => {
  const value = Math.max(1, Math.min(8, Math.trunc(Number(profileCount.value) || 1)));
  $('#run-count-stat').textContent = String(value);
  $('#header-profile-count').textContent = String(value);
  syncProfilePicker();
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
  renderOmniAssignments(value);
  renderHidemiumAssignments(value);
  syncProfilePicker();
  renderProfiles(activeProfileSelection().length, lastSiteLabel, [], activeProfileSelection());
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
  const selection = activeProfileSelection();
  const count = selection.length;
  if (!count) {
    showNotice('Hãy chọn ít nhất một profile trước khi chạy.', true);
    return;
  }
  const indices = selection;
  $('#run-count-stat').textContent = String(count);
  $('#run-table-stat').textContent = '\u0110ang qu\u00e9t...';
  runButton.disabled = true;
  runButton.classList.add('busy');
  showNotice('Ch\u1edd s\u1ea3nh DG t\u1ea3i tr\u00ean c\u00e1c profile v\u00e0 \u0111\u1ed3ng b\u1ed9 v\u00e0o c\u00f9ng b\u00e0n...');
  try {
    const siteIds = indices.map((index) =>
      profileSiteSelections[String(index)] || profileSites[0]?.id || '');
    showNotice('\u0110ang m\u1edf c\u00e1c profile theo site \u0111\u00e3 ch\u1ecdn...');
    const opened = await api.openProfiles(count, siteIds[0], collectSettings(count, indices),
      $('#profile-source').value, $('#omni-api-url').value.trim(), siteIds,
      $('#hidemium-api-url').value.trim(), indices);
    if (!opened?.ok) {
      showNotice(opened?.error || 'Kh\u00f4ng m\u1edf \u0111\u01b0\u1ee3c c\u00e1c profile.', true);
      return;
    }
    renderProfiles(count, opened.site, opened.replies || [], indices);
    $('#close-profiles').disabled = false;
    const openFailures = (opened.replies || []).filter((reply) => !reply.ok);
    if (openFailures.length) {
      showNotice(`${openFailures.length}/${count} profile ch\u01b0a m\u1edf \u0111\u01b0\u1ee3c. Ki\u1ec3m tra danh s\u00e1ch Profile.` , true);
      return;
    }
    indices.forEach((index, offset) => {
      updateProfile(index, 'running', `\u0110\u00e3 m\u1edf site ${opened.replies[offset]?.site || ''}; \u0111ang ch\u1edd v\u00e0o s\u1ea3nh DG.`);
    });
    showNotice('\u0110ang ch\u1edd b\u1ea1n t\u1ef1 v\u00e0o s\u1ea3nh DG. \u1ee8ng d\u1ee5ng s\u1ebd qu\u00e9t tr\u1ea1ng th\u00e1i m\u1ed7i 5 gi\u00e2y...');
    const result = await api.runDGGroup(count, siteIds, indices);
    if (!result || !result.ok) {
      for (const reply of result?.entry_replies || []) {
        updateProfile(reply.index, reply.ok ? 'running' : 'error', reply.ok
          ? `\u0110\u00e3 v\u00e0o s\u1ea3nh DG qua ${reply.site}.`
          : `${reply.site}: ${reply.error || 'ch\u01b0a v\u00e0o \u0111\u01b0\u1ee3c DG.'}`);
      }
      showNotice(result?.error || 'Ch\u01b0a th\u1ec3 \u0111\u1ed3ng b\u1ed9 s\u1ea3nh DG.', true);
      return;
    }
    $('#run-table-stat').textContent = `${result.table_name} \u00b7 ${result.table_id}`;
    renderBetAssignments(result);
    indices.forEach((index) => {
      updateProfile(index, 'running', `\u0110\u00e3 \u0111\u1ed3ng b\u1ed9 v\u00e0o DG ${result.table_id}.`);
    });
    $('#close-profiles').disabled = false;
    showNotice(`C\u1ea3 ${result.count} profile \u0111\u00e3 v\u00e0o ${result.table_name} (${result.table_id}); \u0111ang v\u1eadn h\u00e0nh d\u00e3y c\u01b0\u1ee3c nh\u00f3m.`);
  } catch (error) {
    showNotice(String(error.message || error), true);
  } finally {
    runButton.classList.remove('busy');
    runButton.disabled = profileSites.length === 0 || activeProfileSelection().length === 0;
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
  const row = button.closest('.profile-row');
  const state = profileStateByIndex.get(index);
  const closing = state === 'running' || state === 'opening';
  const site = profileSites.find((item) => item.id === row.querySelector('.profile-site-select')?.value);
  button.disabled = true;
  updateProfile(index, closing ? 'closing' : 'opening', closing ? '\u0110ang \u0111\u00f3ng Chrome\u2026' : '\u0110ang m\u1edf Chrome\u2026');
  try {
    const result = closing
      ? await api.closeProfile(index)
      : await api.openProfile(index, Math.max(1, Math.min(8, Number(profileCount.value) || index)),
        collectSettings(1, [index])[0],
        site?.url, $('#profile-source').value, $('#omni-api-url').value.trim(), $('#hidemium-api-url').value.trim());
    if (!result || !result.ok) {
      updateProfile(index, 'error', result?.error || 'Kh\u00f4ng th\u1ef1c hi\u1ec7n \u0111\u01b0\u1ee3c thao t\u00e1c.');
      return;
    }
    if (closing) {
      updateProfile(index, 'closed', result.note || '\u0110\u00e3 \u0111\u00f3ng profile.');
      showNotice(`\u0110\u00e3 \u0111\u00f3ng Profile ${index}.`);
    } else {
      const dims = result.width && result.height ? ` \u00b7 ${result.width}\u00d7${result.height} \u00b7 ${result.scale}%` : '';
      updateProfile(index, 'opening', `${result.note || '\u0110ang m\u1edf profile.'} \u00b7 ${result.proxy || 'IP tr\u1ef1c ti\u1ebfp'}${dims}`);
      showNotice(`\u0110ang m\u1edf Profile ${index} t\u1ea1i ${site?.label || 'site \u0111\u00e3 ch\u1ecdn'}.`);
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

$('#run-bets').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.classList.add('busy');
  $('#bet-notice').textContent = 'Đang lưu cấu hình và kiểm tra các profile đang mở tại bàn DG...';
  try {
    const result = await api.startBetsOnOpenProfiles(readBetConfig());
    if (!result?.ok) {
      $('#bet-notice').textContent = result?.error || 'Không khởi động được cược trên các profile đang mở.';
      $('#bet-notice').dataset.state = 'error';
      showNotice(result?.error || 'Không khởi động được cược.', true);
      return;
    }
    $('#bet-notice').textContent = `Đã chạy cược cho ${result.count} profile đang mở tại ${result.table_name} (${result.table_id}); Chrome được giữ nguyên.`;
    $('#bet-notice').dataset.state = 'ready';
    $('#run-table-stat').textContent = `${result.table_name} · ${result.table_id}`;
    showNotice($('#bet-notice').textContent);
  } catch (error) {
    $('#bet-notice').textContent = String(error.message || error);
    $('#bet-notice').dataset.state = 'error';
    showNotice($('#bet-notice').textContent, true);
  } finally {
    button.disabled = false;
    button.classList.remove('busy');
  }
});
updateBetPreview();

api.onGroupHop((status) => {
  const target = $('#bet-notice');
  if (!target || !status || !status.note) return;
  for (const profile of status.profile_states || []) {
    updateProfile(profile.index, 'running', profile.note || 'Đang theo dõi sảnh DG.');
  }
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
    profileSites = info.profileSites || [];
    const savedLog = await api.getActivityLog();
    activityLogRows = (savedLog?.rows || []).slice(-5000);
    renderActivityLog();
    try { profileSiteSelections = JSON.parse(localStorage.getItem('aibcr.profileSites') || '{}') || {}; }
    catch { profileSiteSelections = {}; }
    selectedProfileIndices = readStoredSelection();
    profileSelectionTouched = selectedProfileIndices.length > 0;
    const betConfig = await api.getBetConfig();
    if (betConfig && betConfig.ok) fillBetConfig(betConfig.config || {});
    setProxyState(await api.listProxies());
    const savedSource = localStorage.getItem(PROFILE_SOURCE_KEY);
    $('#profile-source').value = ['omni', 'hidemium'].includes(savedSource) ? savedSource : 'local';
    $('#omni-api-url').value = localStorage.getItem(OMNI_API_KEY) || 'http://127.0.0.1:35353';
    $('#hidemium-api-url').value = localStorage.getItem(HIDEMIUM_API_KEY) || 'http://127.0.0.1:5555';
    try { omniAssignments = JSON.parse(localStorage.getItem(OMNI_ASSIGNMENTS_KEY) || '{}') || {}; } catch { omniAssignments = {}; }
    try { hidemiumAssignments = JSON.parse(localStorage.getItem(HIDEMIUM_ASSIGNMENTS_KEY) || '{}') || {}; } catch { hidemiumAssignments = {}; }
    renderOmniAssignments(Math.max(1, Math.min(8, Number(profileCount.value) || 1)));
    renderHidemiumAssignments(Math.max(1, Math.min(8, Number(profileCount.value) || 1)));
    syncProfilePicker();
    renderProfiles(activeProfileSelection().length, lastSiteLabel, [], activeProfileSelection());
    updateSitePreview();
    showNotice('');
  } catch (error) {
    showNotice(`Không tải được danh sách website: ${error.message || error}`, true);
  }
})();
