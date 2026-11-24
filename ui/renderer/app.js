const api = window.aibcr;
const $ = (selector) => document.querySelector(selector);
const MAX_PROFILES = 8;
const selectedIndicesOrDefault = () => (selectedProfileIndices.length
  ? selectedProfileIndices : Array.from({ length: MAX_PROFILES }, (_, i) => i + 1));
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
    row.className = `activity-log-row ${item.level === 'error' ? 'error' : ''}`
      + `${item.level === 'action' ? ' action' : ''}`;
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
  // Same behaviour as the reference tool: critical failures ring a siren.
  window.aibcrAlarm?.notify?.(item.text, { level: item.level });
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
  const text = String(message == null ? '' : message).trim();
  notice.textContent = message;
  notice.dataset.state = isError ? 'error' : 'ready';
  // Cùng một thông điệp hiện ở khung notice và toast để người dùng đang ở tab
  // khác vẫn thấy phản hồi; toast tự chống trùng lặp trong 1,2 giây.
  if (!text) return;
  const toast = window.aibcrToast;
  if (!toast) return;
  if (isError) toast.error(text);
  else toast.info(text);
}

function profileIndex(game) {
  if (game === 'baccarat') return 1;
  const match = /^baccarat-profile-(\d+)$/.exec(game || '');
  return match ? Number(match[1]) : 0;
}

function updateProfile(index, state, detail = '') {
  const row = statusByIndex.get(index);
  profileStateByIndex.set(index, state);
  mirrorProviderState(index, state);
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
    const chosen = selectedIndicesOrDefault().includes(index);
    row.className = `profile-row ${state}${chosen ? ' profile-selected' : ''}`;
    row.innerHTML = `<div class="profile-number">${String(index).padStart(2, '0')}</div>
      <div class="profile-info"><strong>Profile ${index}</strong><span class="profile-detail"></span></div>
      <select class="profile-site-select" data-profile="${index}" aria-label="Site c\u1ee7a Profile ${index}"></select>
      <span class="profile-state"></span><button class="profile-toggle" data-profile="${index}">M\u1edf</button>
      <button class="profile-fingerprint" data-profile="${index}" title="\u0110\u1ed5i d\u1ea5u v\u1ebft thi\u1ebft b\u1ecb Android">D\u1ea5u v\u1ebft</button>`;
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
    const detail = [reply.note || reply.error || '', reply.device || '']
      .filter(Boolean).join(' \u00b7 ');
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
  syncProfileSubtabs();
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
  // Default count when nothing has been chosen yet: every slot up to MAX_PROFILES.
  return MAX_PROFILES;
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
  const countLabel = $('#selection-count');
  if (countLabel) {
    countLabel.textContent = selection.size
      ? `${selection.size} profile · ${[...selection].sort((a, b) => a - b).map((index) => `P${index}`).join(', ')}`
      : 'Chưa chọn profile';
  }
  if (profileSites.length) runButton.disabled = selection.size === 0;
  syncProfileSubtabs();
}

const THEME_KEY = 'aibcr.theme';

function applyTheme(theme) {
  const next = theme === 'light' ? 'light' : 'dark';
  // theme.js là nơi duy nhất ghi data-theme + localStorage; app.js chỉ điều
  // khiển nút, nhờ vậy hai nơi không ghi đè nhau khi bấm nút ở titlebar.
  if (window.aibcrTheme) window.aibcrTheme.apply(next);
  else {
    document.documentElement.dataset.theme = next;
    localStorage.setItem(THEME_KEY, next);
    document.documentElement.style.colorScheme = next;
  }
  const toggle = $('#theme-toggle');
  if (toggle) {
    toggle.setAttribute('aria-pressed', String(next === 'light'));
    toggle.title = next === 'light' ? 'Chuyển sang giao diện tối' : 'Chuyển sang giao diện sáng';
  }
}

function initTheme() {
  // theme.js đã áp màu trong <head> để tránh nháy sáng/tối; ở đây chỉ đồng bộ
  // lại trạng thái nút và nối sự kiện chuyển đổi.
  const saved = localStorage.getItem(THEME_KEY);
  applyTheme(saved || document.documentElement.dataset.theme || 'dark');
  $('#theme-toggle').addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
  });
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
const PROFILE_SUBTAB_KEY = 'aibcr.profileSubtab';
// Reconnect without re-configuring: restore the manager, API URL and profile
// choice remembered from the last successful connection.
async function restoreRememberedConnections() {
  let store = { profiles: {} };
  try { store = await api.loadProfileConnections(); } catch { return; }
  const entries = Object.entries(store?.profiles || {});
  if (!entries.length) return;

  const savedSource = localStorage.getItem(PROFILE_SOURCE_KEY);
  const providers = new Set(entries.map(([, item]) => item.provider).filter(Boolean));
  const source = savedSource || (providers.has('omni') ? 'omni'
    : providers.has('hidemium') ? 'hidemium' : '');
  if (source) {
    const select = $('#profile-source');
    if (select && [...select.options].some((option) => option.value === source)) {
      select.value = source;
    }
  }

  const omniEntry = entries.find(([, item]) => item.provider === 'omni');
  if (omniEntry?.[1]?.apiUrl && $('#omni-api-url')) {
    $('#omni-api-url').value = omniEntry[1].apiUrl
      || localStorage.getItem(OMNI_API_KEY) || $('#omni-api-url').value;
  }
  const hidemiumEntry = entries.find(([, item]) => item.provider === 'hidemium');
  if (hidemiumEntry?.[1]?.apiUrl && $('#hidemium-api-url')) {
    $('#hidemium-api-url').value = hidemiumEntry[1].apiUrl
      || localStorage.getItem(HIDEMIUM_API_KEY) || $('#hidemium-api-url').value;
  }

  // Assignments can only be shown when the manager's profile list is loaded.
  // Refresh it for the remembered provider so the selects have real options.
  try {
    if (source === 'omni' && $('#omni-api-url').value.trim()) {
      const result = await api.listOmniProfiles($('#omni-api-url').value.trim());
      if (result?.ok) {
        omniProfiles = result.profiles || [];
        setProviderStatus('omni', `${omniProfiles.length} profile khả dụng`,
          omniProfiles.length ? 'ready' : 'idle');
      }
    } else if (source === 'hidemium' && $('#hidemium-api-url').value.trim()) {
      const result = await api.listHidemiumProfiles($('#hidemium-api-url').value.trim());
      if (result?.ok) {
        hidemiumProfiles = result.profiles || [];
        setProviderStatus('hidemium', `${hidemiumProfiles.length} profile khả dụng`,
          hidemiumProfiles.length ? 'ready' : 'idle');
      }
    }
  } catch (error) {
    // Manager may be closed; keep the saved ids and let the user reconnect.
  }

  const restored = [];
  for (const [profileIndex, item] of entries) {
    if (!item?.profileId) continue;
    const key = String(profileIndex);
    if (item.provider === 'omni') omniAssignments[key] = String(item.profileId);
    if (item.provider === 'hidemium') hidemiumAssignments[key] = String(item.profileId);
    restored.push(Number(profileIndex));
  }
  localStorage.setItem(OMNI_ASSIGNMENTS_KEY, JSON.stringify(omniAssignments));
  localStorage.setItem(HIDEMIUM_ASSIGNMENTS_KEY, JSON.stringify(hidemiumAssignments));

  // Adopt the remembered profiles as the selection. A stale selection from a
  // previous run (for example P4) must not win over what actually reconnects.
  const chosen = activeProfileSelection();
  const alreadyChosen = restored.every((index) => chosen.includes(index));
  if (restored.length && (!alreadyChosen || chosen.length !== restored.length)) {
    selectedProfileIndices = [...new Set(restored)].sort((a, b) => a - b);
    localStorage.setItem(PROFILE_SELECTION_KEY, JSON.stringify(selectedProfileIndices));
    profileSelectionTouched = true;
  }
  renderProviderAssignments('omni');
  renderProviderAssignments('hidemium');
  showNotice(`Đã khôi phục kết nối cũ cho profile ${restored.join(', ')}.`);
}

// Tab con của tab Profiles: mỗi nguồn profile một trang riêng (Chrome / OmniLogin
// / Hidemium) thay vì dồn cả ba vào một trang dài. Cả ba dùng chung khuôn gán
// slot P1–P8 nên phần render/ghi nhớ chỉ viết một lần.
const PROVIDERS = {
  omni: {
    key: 'omni',
    source: 'omni',
    label: 'OmniLogin',
    host: '#omni-profile-assignments',
    connect: '#omni-refresh',
    search: '#omni-search',
    notice: '#omni-notice',
    status: '#omni-status',
    badge: '#subtab-count-omni',
    apiInput: '#omni-api-url',
    assignAll: '#omni-assign-all',
    openAll: '#omni-open-all',
    closeAll: '#omni-close-all',
    clear: '#omni-clear',
    apiKey: OMNI_API_KEY,
    storageKey: OMNI_ASSIGNMENTS_KEY,
  },
  hidemium: {
    key: 'hidemium',
    source: 'hidemium',
    label: 'Hidemium',
    host: '#hidemium-profile-assignments',
    connect: '#hidemium-refresh',
    search: '#hidemium-search',
    notice: '#hidemium-notice',
    status: '#hidemium-status',
    badge: '#subtab-count-hidemium',
    apiInput: '#hidemium-api-url',
    assignAll: '#hidemium-assign-all',
    openAll: '#hidemium-open-all',
    closeAll: '#hidemium-close-all',
    clear: '#hidemium-clear',
    apiKey: HIDEMIUM_API_KEY,
    storageKey: HIDEMIUM_ASSIGNMENTS_KEY,
  },
};

// Trạng thái mở/đóng theo từng dòng của provider, tách khỏi statusByIndex của
// danh sách Profile Chrome để hai tab con không ghi đè lẫn nhau.
const providerOpenState = new Map();
const providerStateKey = (key, index) => `${key}:${index}`;

// Trạng thái do luồng Chạy Tool/Đóng tất cả thay đổi phải hiện luôn ở tab con
// provider, nếu không hai nơi sẽ nói khác nhau về cùng một profile. Chỉ đồng bộ
// những slot đã từng được mở từ tab provider: mở Chrome local không có nghĩa là
// profile OmniLogin/Hidemium tương ứng đang chạy.
let mirroringProviderState = false;
function mirrorProviderState(index, state) {
  if (mirroringProviderState) return;
  const keys = Object.keys(PROVIDERS)
    .filter((key) => providerOpenState.has(providerStateKey(key, index)));
  if (!keys.length) return;
  for (const key of keys) providerOpenState.set(providerStateKey(key, index), state);
  mirroringProviderState = true;
  try {
    for (const key of keys) {
      if ($(PROVIDERS[key].host)?.children.length) renderProviderAssignments(key);
    }
  } finally {
    mirroringProviderState = false;
  }
}

function providerProfiles(key) {
  return key === 'omni' ? omniProfiles : hidemiumProfiles;
}

function setProviderProfiles(key, list) {
  if (key === 'omni') omniProfiles = list;
  else hidemiumProfiles = list;
}

function providerAssignments(key) {
  return key === 'omni' ? omniAssignments : hidemiumAssignments;
}

function setProviderAssignments(key, next) {
  if (key === 'omni') omniAssignments = next;
  else hidemiumAssignments = next;
  localStorage.setItem(PROVIDERS[key].storageKey, JSON.stringify(next));
}

function providerAssignedCount(key) {
  const profiles = providerProfiles(key);
  return Object.values(providerAssignments(key))
    .filter((id) => profiles.some((profile) => profile.id === id)).length;
}

function setProviderStatus(key, text, state = 'idle') {
  const node = $(PROVIDERS[key].status);
  if (!node) return;
  node.textContent = text;
  node.dataset.state = state;
}

// Badge số lượng trên thanh tab con, cập nhật sau mỗi lần gán/kết nối.
function syncProfileSubtabs() {
  const chromeBadge = $('#subtab-count-chrome');
  if (chromeBadge) {
    const count = activeProfileSelection().length;
    chromeBadge.textContent = String(count);
    chromeBadge.dataset.state = count ? 'ready' : 'idle';
  }
  for (const key of Object.keys(PROVIDERS)) {
    const node = $(PROVIDERS[key].badge);
    if (!node) continue;
    const count = providerAssignedCount(key);
    node.textContent = String(count);
    node.dataset.state = count ? 'ready' : 'idle';
  }
}

function providerOptionLabel(profile) {
  return profile.name && profile.name !== profile.id ? `${profile.name} · ${profile.id}` : profile.id;
}

function renderProviderAssignments(key, count = MAX_PROFILES) {
  const spec = PROVIDERS[key];
  const host = $(spec.host);
  if (!host) return;
  const profiles = providerProfiles(key);
  const assignments = providerAssignments(key);
  const query = ($(spec.search)?.value || '').trim().toLowerCase();
  // Tìm kiếm lọc chính danh sách option của từng slot (không ẩn slot), để người
  // dùng luôn thấy đủ P1–P8 và chỉ thu hẹp lựa chọn khi gán.
  const matches = query
    ? profiles.filter((profile) => `${profile.name} ${profile.id}`.toLowerCase().includes(query))
    : profiles;
  host.replaceChildren();
  for (let index = 1; index <= count; index += 1) {
    const chosen = assignments[String(index)] || '';
    const known = Boolean(chosen) && profiles.some((profile) => profile.id === chosen);
    const row = document.createElement('div');
    row.className = `provider-assignment${known ? ' assigned' : ''}`;
    row.dataset.profile = String(index);
    row.innerHTML = `<span class="provider-slot">P${index}</span><select></select>
      <select class="provider-site-select" data-profile="${index}"
        aria-label="Site của Profile ${index}"></select>
      <span class="provider-row-state"></span>
      <button class="provider-row-toggle" type="button" data-profile="${index}">Mở</button>`;
    const select = row.querySelector('select:not(.provider-site-select)');
    select.dataset.profile = String(index);
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = profiles.length
      ? (query && !matches.length ? 'Không khớp từ khoá' : 'Chưa gán profile')
      : 'Kết nối API để tải profiles';
    select.append(empty);
    // Giữ option đang gán kể cả khi nó không khớp từ khoá, nếu không select sẽ
    // nhảy về rỗng và người dùng tưởng profile bị bỏ gán.
    const options = known && !matches.some((profile) => profile.id === chosen)
      ? [...matches, profiles.find((profile) => profile.id === chosen)].filter(Boolean)
      : matches;
    for (const profile of options) {
      const option = document.createElement('option');
      option.value = profile.id;
      option.textContent = providerOptionLabel(profile);
      select.append(option);
    }
    select.value = known ? chosen : '';

    // Ô chọn site riêng cho từng slot — giống hệt danh sách ở tab Profile Chrome,
    // để profile OmniLogin/Hidemium mở đúng site người dùng muốn (mặc định site
    // đầu tiên). Không có ô này thì mọi slot luôn mở site đầu danh sách và người
    // dùng không cấu hình được gì.
    const siteSelect = row.querySelector('.provider-site-select');
    siteSelect.replaceChildren();
    for (const site of profileSites) {
      const option = document.createElement('option');
      option.value = site.id;
      option.textContent = site.display || site.label;
      siteSelect.append(option);
    }
    const savedSite = profileSiteSelections[String(index)];
    const pickedSite = profileSites.some((site) => site.id === savedSite)
      ? savedSite : profileSites[0]?.id || '';
    if (pickedSite) {
      siteSelect.value = pickedSite;
      profileSiteSelections[String(index)] = pickedSite;
    }
    siteSelect.disabled = !profileSites.length;
    localStorage.setItem('aibcr.profileSites', JSON.stringify(profileSiteSelections));

    const state = providerOpenState.get(providerStateKey(key, index)) || 'closed';
    const stateNode = row.querySelector('.provider-row-state');
    // Cửa sổ có thể vẫn đang mở dù người dùng đã bấm "Bỏ gán"; khi đó vẫn phải hiện
    // trạng thái thật và cho đóng, tránh màn hình nói "Chưa gán" trong lúc Chrome chạy.
    const live = state !== 'closed';
    stateNode.textContent = state === 'running' ? 'Đang mở'
      : state === 'opening' ? 'Đang mở…' : state === 'closing' ? 'Đang đóng…'
        : state === 'error' ? 'Có lỗi' : known ? 'Chưa mở' : 'Chưa gán';
    stateNode.dataset.state = known || live ? state : 'unset';
    row.dataset.assigned = known ? 'yes' : 'no';
    row.classList.toggle('live', live);
    const toggle = row.querySelector('.provider-row-toggle');
    const canClose = known || state === 'running';
    toggle.textContent = state === 'running' || state === 'opening' ? 'Đóng' : 'Mở';
    toggle.disabled = !canClose || state === 'opening' || state === 'closing';
    host.append(row);
  }
  if (!host.children.length) {
    const empty = document.createElement('p');
    empty.className = 'provider-empty';
    empty.textContent = `Chưa có profile ${spec.label}. Bấm Kết nối để tải danh sách từ API cục bộ.`;
    host.append(empty);
  }
  syncProfileSubtabs();
}

async function connectProvider(key) {
  const spec = PROVIDERS[key];
  const button = $(spec.connect);
  button.disabled = true;
  setProviderStatus(key, 'Đang kết nối…', 'pending');
  $(spec.notice).textContent = `Đang kết nối API ${spec.label}…`;
  try {
    const apiUrl = $(spec.apiInput).value.trim();
    const result = key === 'omni'
      ? await api.listOmniProfiles(apiUrl) : await api.listHidemiumProfiles(apiUrl);
    if (!result?.ok) throw new Error(result?.error || `Không tải được profiles ${spec.label}.`);
    const list = result.profiles || [];
    setProviderProfiles(key, list);
    $(spec.apiInput).value = result.apiUrl;
    localStorage.setItem(spec.apiKey, result.apiUrl);
    // Bỏ gán trỏ tới profile đã bị xoá ở provider để lần chạy sau không lỗi.
    setProviderAssignments(key, Object.fromEntries(Object.entries(providerAssignments(key))
      .filter(([, id]) => list.some((profile) => profile.id === id))));
    renderProviderAssignments(key);
    setProviderStatus(key, `${list.length} profile khả dụng`, list.length ? 'ready' : 'idle');
    $(spec.notice).textContent = `${spec.label} kết nối thành công · ${list.length} profiles.`;
    window.aibcrToast?.success(`${spec.label}: đã tải ${list.length} profile.`);
  } catch (error) {
    const message = String(error.message || error);
    setProviderStatus(key, 'Lỗi kết nối', 'error');
    $(spec.notice).textContent = message;
    window.aibcrToast?.error(message, { title: spec.label });
  } finally {
    button.disabled = false;
  }
}

// Gán lần lượt danh sách profile của provider vào các slot đang chọn, bỏ qua
// slot đã có profile hợp lệ và không dùng lại cùng một profile hai lần.
function assignProviderSequentially(key) {
  const spec = PROVIDERS[key];
  const profiles = providerProfiles(key);
  if (!profiles.length) {
    $(spec.notice).textContent = `Kết nối ${spec.label} trước khi gán profile.`;
    return;
  }
  const slots = activeProfileSelection().length
    ? activeProfileSelection() : Array.from({ length: MAX_PROFILES }, (_, offset) => offset + 1);
  const next = { ...providerAssignments(key) };
  const used = new Set(Object.values(next));
  let cursor = 0;
  let assigned = 0;
  for (const index of slots) {
    const current = next[String(index)];
    if (current && profiles.some((profile) => profile.id === current)) continue;
    while (cursor < profiles.length && used.has(profiles[cursor].id)) cursor += 1;
    if (cursor >= profiles.length) break;
    next[String(index)] = profiles[cursor].id;
    used.add(profiles[cursor].id);
    cursor += 1;
    assigned += 1;
  }
  setProviderAssignments(key, next);
  renderProviderAssignments(key);
  $(spec.notice).textContent = assigned
    ? `Đã gán ${assigned} profile ${spec.label} cho ${slots.length} slot đang chọn.`
    : `Các slot đang chọn đã có profile ${spec.label} hợp lệ.`;
  // Phân biệt "gán thêm được" với "slot đã đủ profile", tránh báo sai là hết profile.
  window.aibcrToast?.info(assigned
    ? `${spec.label}: gán ${assigned} profile.`
    : `Slot đang chọn đã có profile ${spec.label}.`);
}

function clearProviderAssignments(key) {
  const spec = PROVIDERS[key];
  setProviderAssignments(key, {});
  renderProviderAssignments(key);
  $(spec.notice).textContent = `Đã bỏ toàn bộ gán ${spec.label}.`;
  window.aibcrToast?.info(`Đã bỏ gán ${spec.label}.`);
}

// Mở/đóng ngay tại dòng của provider. Dùng chung IPC profile:open/close nên
// Chrome mở ra chính là profile của OmniLogin/Hidemium, không phải cửa sổ mới.
async function toggleProviderProfile(key, index) {
  const spec = PROVIDERS[key];
  const state = providerOpenState.get(providerStateKey(key, index)) || 'closed';
  const running = state === 'running' || state === 'opening';
  const profileId = providerAssignments(key)[String(index)] || '';
  providerOpenState.set(providerStateKey(key, index), running ? 'closing' : 'opening');
  renderProviderAssignments(key);
  try {
    let result;
    if (running) {
      result = await api.closeProfile(index);
    } else {
      const siteId = profileSiteSelections[String(index)] || profileSites[0]?.id;
      const site = profileSites.find((item) => item.id === siteId);
      result = await api.openProfile(index, MAX_PROFILES, collectSettings(1, [index])[0],
        site?.url, spec.source, $('#omni-api-url').value.trim(), $('#hidemium-api-url').value.trim());
    }
    if (!result?.ok) {
      providerOpenState.set(providerStateKey(key, index), 'error');
      renderProviderAssignments(key);
      $(spec.notice).textContent = result?.error || `Không thao tác được profile ${spec.label}.`;
      window.aibcrToast?.error(result?.error || 'Không thao tác được profile.', { title: spec.label });
      return;
    }
    providerOpenState.set(providerStateKey(key, index), running ? 'closed' : 'running');
    renderProviderAssignments(key);
    const detail = running
      ? `Đã đóng ${spec.label} · P${index}.`
      : `Đã mở ${spec.label} ${profileId} · P${index}.`;
    $(spec.notice).textContent = detail;
    window.aibcrToast?.success(detail);
    // Đồng bộ sang danh sách Profile Chrome để hai tab con luôn khớp trạng thái.
    updateProfile(index, running ? 'closed' : 'running', detail);
  } catch (error) {
    providerOpenState.set(providerStateKey(key, index), 'error');
    renderProviderAssignments(key);
    $(spec.notice).textContent = String(error.message || error);
  }
}

// Mở/đóng toàn bộ slot đã gán của provider. Mở tuần tự để không mở 8 cửa sổ
// cùng lúc (provider dễ nghẽn cổng CDP) và báo tiến độ theo từng dòng.
async function openAllProviderProfiles(key) {
  const spec = PROVIDERS[key];
  const assignments = providerAssignments(key);
  // Bỏ qua slot đang mở/đang chuyển: mở lại sẽ lỗi vì cửa sổ đã tồn tại.
  const skipped = [];
  const indices = Object.keys(assignments)
    .map(Number).filter((index) => Number.isInteger(index))
    .sort((a, b) => a - b)
    .filter((index) => {
      const state = providerOpenState.get(providerStateKey(key, index)) || 'closed';
      if (state === 'closed' || state === 'error') return true;
      skipped.push(index);
      return false;
    });
  if (!indices.length) {
    const message = skipped.length
      ? `${spec.label}: ${skipped.length} profile đã mở sẵn.`
      : `Chưa gán profile ${spec.label} nào để mở.`;
    $(spec.notice).textContent = message;
    window.aibcrToast?.warning(message);
    return;
  }
  $(spec.openAll).disabled = true;
  // Mỗi slot dùng site riêng đã chọn ở tab Profile Chrome, giống nút Mở từng dòng;
  // chỉ khi slot chưa chọn site mới rơi về site đầu tiên.
  const siteFor = (index) => {
    const siteId = profileSiteSelections[String(index)] || profileSites[0]?.id;
    return profileSites.find((item) => item.id === siteId) || profileSites[0];
  };
  let opened = 0;
  const failures = [];
  try {
    for (const index of indices) {
      const site = siteFor(index);
      providerOpenState.set(providerStateKey(key, index), 'opening');
      renderProviderAssignments(key);
      let reply;
      try {
        reply = await api.openProfile(index, MAX_PROFILES, collectSettings(1, [index])[0],
          site?.url, spec.source, $('#omni-api-url').value.trim(), $('#hidemium-api-url').value.trim());
      } catch (error) {
        reply = { ok: false, error: String(error.message || error) };
      }
      if (reply?.ok) {
        opened += 1;
        providerOpenState.set(providerStateKey(key, index), 'running');
        updateProfile(index, 'running', reply.note || `Đã mở ${spec.label}.`);
      } else {
        failures.push(index);
        providerOpenState.set(providerStateKey(key, index), 'error');
      }
      renderProviderAssignments(key);
    }
    const message = failures.length
      ? `${spec.label}: mở ${opened}/${indices.length}${skipped.length ? ` · ${skipped.length} đã mở sẵn` : ''}, lỗi ở P${failures.join(', P')}.`
      : `${spec.label}: đã mở ${opened} profile${skipped.length ? ` · ${skipped.length} đã mở sẵn` : ''}.`;
    $(spec.notice).textContent = message;
    if (failures.length) window.aibcrToast?.warning(message, { title: spec.label });
    else window.aibcrToast?.success(message, { title: spec.label });
  } finally {
    $(spec.openAll).disabled = false;
  }
}

async function closeAllProviderProfiles(key) {
  const spec = PROVIDERS[key];
  // Lấy theo trạng thái mở thay vì theo danh sách gán: người dùng có thể đã bấm
  // "Bỏ gán" trong khi cửa sổ vẫn đang mở, và những cửa sổ đó vẫn phải đóng được.
  const indices = [...providerOpenState.entries()]
    .filter(([stateKey, state]) => stateKey.startsWith(`${key}:`) && state !== 'closed')
    .map(([stateKey]) => Number(stateKey.slice(key.length + 1)))
    .filter((index) => Number.isInteger(index))
    .sort((a, b) => a - b);
  if (!indices.length) {
    $(spec.notice).textContent = `Không có profile ${spec.label} nào đang mở.`;
    return;
  }
  $(spec.closeAll).disabled = true;
  let closed = 0;
  try {
    for (const index of indices) {
      providerOpenState.set(providerStateKey(key, index), 'closing');
      renderProviderAssignments(key);
      try {
        const reply = await api.closeProfile(index);
        if (reply?.ok) closed += 1;
      } catch { /* dòng lỗi được đánh dấu bên dưới */ }
      providerOpenState.set(providerStateKey(key, index), 'closed');
      renderProviderAssignments(key);
      updateProfile(index, 'closed', `Đã đóng ${spec.label}.`);
    }
    const message = `${spec.label}: đã đóng ${closed}/${indices.length} profile.`;
    $(spec.notice).textContent = message;
    window.aibcrToast?.success(message, { title: spec.label });
  } finally {
    $(spec.closeAll).disabled = false;
  }
}

for (const key of Object.keys(PROVIDERS)) {
  const spec = PROVIDERS[key];
  $(spec.connect).addEventListener('click', () => connectProvider(key));
  $(spec.apiInput).addEventListener('change', () => localStorage.setItem(
    spec.apiKey, $(spec.apiInput).value.trim()));
  $(spec.search).addEventListener('input', () => renderProviderAssignments(key));
  $(spec.assignAll).addEventListener('click', () => assignProviderSequentially(key));
  $(spec.openAll).addEventListener('click', () => openAllProviderProfiles(key));
  $(spec.closeAll).addEventListener('click', () => closeAllProviderProfiles(key));
  $(spec.clear).addEventListener('click', () => clearProviderAssignments(key));
  $(spec.host).addEventListener('change', (event) => {
    // Có hai select mang ``data-profile`` trong mỗi dòng: gán profile provider và
    // chọn site riêng. Phân biệt bằng class để đổi site không bị hiểu nhầm thành
    // đổi profile đang gán (và ngược lại).
    const siteSelect = event.target.closest('select.provider-site-select');
    if (siteSelect) {
      const index = siteSelect.dataset.profile;
      if (!siteSelect.value) return;
      profileSiteSelections[index] = siteSelect.value;
      localStorage.setItem('aibcr.profileSites', JSON.stringify(profileSiteSelections));
      const label = profileSites.find((site) => site.id === siteSelect.value)?.label
        || siteSelect.value;
      $(spec.notice).textContent = `P${index} sẽ mở site ${label}.`;
      // Tab Profile Chrome hiển thị cùng lựa chọn này, nên phải vẽ lại để hai nơi
      // không nói hai kiểu.
      const chromeSelect = profileList.querySelector(
        `.profile-site-select[data-profile="${index}"]`);
      if (chromeSelect) chromeSelect.value = siteSelect.value;
      return;
    }
    const select = event.target.closest('select[data-profile]');
    if (!select) return;
    const index = select.dataset.profile;
    const next = { ...providerAssignments(key) };
    if (select.value) next[index] = select.value;
    else delete next[index];
    setProviderAssignments(key, next);
    renderProviderAssignments(key);
    $(spec.notice).textContent = select.value
      ? `Đã gán ${spec.label} cho P${index}.`
      : `Đã bỏ gán ${spec.label} ở P${index}.`;
  });
  $(spec.host).addEventListener('click', (event) => {
    const toggle = event.target.closest('.provider-row-toggle');
    if (!toggle) return;
    toggleProviderProfile(key, Number(toggle.dataset.profile));
  });
}

// --------------------------------------------------------------- tab con nguồn

function updateSubtabHint() {
  const hint = $('#profile-source-hint');
  if (!hint) return;
  const source = $('#profile-source')?.value || 'local';
  const labels = { local: 'Chrome riêng của ứng dụng', omni: 'OmniLogin', hidemium: 'Hidemium' };
  hint.textContent = `Nguồn đang chạy: ${labels[source] || labels.local}`;
}

function setProfileSubtab(name, { applySource = true } = {}) {
  const next = ['chrome', 'omni', 'hidemium'].includes(name) ? name : 'chrome';
  document.querySelectorAll('[data-subtab-target]').forEach((button) => {
    const active = button.dataset.subtabTarget === next;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll('[data-subtab-panel]').forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.subtabPanel === next);
  });
  localStorage.setItem(PROFILE_SUBTAB_KEY, next);
  if (next !== 'chrome') renderProviderAssignments(next);
  if (applySource) {
    const select = $('#profile-source');
    const source = next === 'chrome' ? 'local' : next;
    if (select && [...select.options].some((option) => option.value === source)) {
      select.value = source;
      localStorage.setItem(PROFILE_SOURCE_KEY, source);
      updateSitePreview();
    }
  }
  updateSubtabHint();
}

document.querySelectorAll('[data-subtab-target]').forEach((button) => {
  button.addEventListener('click', () => setProfileSubtab(button.dataset.subtabTarget));
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
  renderProxyAssignments(MAX_PROFILES);
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
  // Tab OmniLogin/Hidemium dùng chung lựa chọn site này; cập nhật luôn để người
  // dùng thấy một site duy nhất cho mỗi slot ở cả hai nơi.
  for (const key of Object.keys(PROVIDERS)) {
    const mirror = document.querySelector(
      `${PROVIDERS[key].host} .provider-site-select[data-profile="${select.dataset.profile}"]`);
    if (mirror) mirror.value = select.value;
  }
});
$('#profile-source').addEventListener('change', () => {
  localStorage.setItem(PROFILE_SOURCE_KEY, $('#profile-source').value);
  // Chọn nguồn ở ô "Nguồn profile" cũng nhảy sang tab con tương ứng để người
  // dùng thấy ngay danh sách profile của nguồn đó.
  const source = $('#profile-source').value;
  setProfileSubtab(source === 'local' ? 'chrome' : source, { applySource: false });
  updateSubtabHint();
  updateSitePreview();
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
$('#save-profile-selection').addEventListener('click', () => {
  const selection = activeProfileSelection();
  if (!selection.length) {
    showNotice('Hãy chọn ít nhất một profile trước khi lưu.', true);
    return;
  }
  profileSelectionTouched = true;
  localStorage.setItem(PROFILE_SELECTION_KEY, JSON.stringify(selection));
  renderProfiles(MAX_PROFILES, lastSiteLabel, [], selectedIndicesOrDefault());
  $('#header-profile-count').textContent = String(selection.length);
  showNotice(`Đã lưu lựa chọn ${selection.map((index) => `P${index}`).join(', ')}.`);
});

// Lối tắt cho tab Profile Chrome: chọn nhanh toàn bộ P1–P8 hoặc bỏ chọn hết,
// và đóng mọi cửa sổ Chrome đang mở mà không phải quay lại tab Chạy Tool.
function setSelection(indices, message) {
  selectedProfileIndices = [...new Set(indices)].sort((a, b) => a - b);
  profileSelectionTouched = true;
  localStorage.setItem(PROFILE_SELECTION_KEY, JSON.stringify(selectedProfileIndices));
  syncProfilePicker();
  renderProfiles(MAX_PROFILES, lastSiteLabel, [], selectedIndicesOrDefault());
  showNotice(message);
}

$('#profile-select-all').addEventListener('click', () => {
  setSelection(Array.from({ length: MAX_PROFILES }, (_, offset) => offset + 1),
    `Đã chọn tất cả P1–P${MAX_PROFILES}.`);
});

$('#profile-select-none').addEventListener('click', () => {
  if (!window.confirm('Bỏ chọn toàn bộ profile? Nút Chạy Tool sẽ cần chọn lại.')) return;
  setSelection([], 'Đã bỏ chọn toàn bộ profile.');
});

// Mở các profile Chrome đang chọn (không đồng bộ DG) — dùng khi chỉ cần dựng
// sẵn cửa sổ để kiểm tra site/proxy trước khi bấm Chạy Tool.
$('#profile-open-selected').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  const indices = activeProfileSelection();
  if (!indices.length) {
    showNotice('Hãy chọn ít nhất một profile trước khi mở.', true);
    return;
  }
  button.disabled = true;
  const source = $('#profile-source').value;
  try {
    for (const index of indices) updateProfile(index, 'opening', 'Đang mở Chrome…');
    const results = await Promise.allSettled(indices.map((index) => {
      const siteId = profileSiteSelections[String(index)] || profileSites[0]?.id;
      const site = profileSites.find((item) => item.id === siteId);
      return api.openProfile(index, MAX_PROFILES, collectSettings(1, [index])[0],
        site?.url, source, $('#omni-api-url').value.trim(), $('#hidemium-api-url').value.trim());
    }));
    let opened = 0;
    const failures = [];
    results.forEach((result, offset) => {
      const index = indices[offset];
      const reply = result.status === 'fulfilled' ? result.value : { ok: false, error: result.reason?.message };
      if (reply?.ok) {
        opened += 1;
        const dims = reply.width && reply.height ? ` · ${reply.width}×${reply.height} · ${reply.scale}%` : '';
        updateProfile(index, 'running', `${reply.note || 'Đang mở profile.'}${dims}`);
      } else {
        failures.push(index);
        updateProfile(index, 'error', reply?.error || 'Không mở được profile.');
      }
    });
    if (failures.length) {
      showNotice(`Mở ${opened}/${indices.length} profile · lỗi ở P${failures.join(', P')}.`, true);
    } else {
      showNotice(`Đã mở ${opened} profile Chrome theo site đã chọn.`);
    }
  } catch (error) {
    showNotice(String(error.message || error), true);
  } finally {
    button.disabled = false;
    $('#close-profiles').disabled = false;
  }
});

$('#profile-close-all').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const result = await api.closeProfiles();
    if (!result?.ok) {
      showNotice(result?.error || 'Không đóng được các profile.', true);
      return;
    }
    for (const index of profileStateByIndex.keys()) updateProfile(index, 'closed', 'Đã đóng Chrome profile.');
    showNotice(`Đã gửi lệnh đóng ${result.count} cửa sổ Chrome.`);
  } catch (error) {
    showNotice(String(error.message || error), true);
  } finally {
    button.disabled = false;
    $('#close-profiles').disabled = true;
  }
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
    renderProfiles(MAX_PROFILES, opened.site, opened.replies || [], selectedIndicesOrDefault());
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
  const fingerprintButton = event.target.closest('.profile-fingerprint');
  if (fingerprintButton) {
    const fingerprintIndex = Number(fingerprintButton.dataset.profile);
    fingerprintButton.disabled = true;
    try {
      const result = await api.regenerateProfileFingerprint(fingerprintIndex);
      if (!result?.ok) {
        showNotice(result?.error || 'Không đổi được dấu vết thiết bị.', true);
        return;
      }
      const row = fingerprintButton.closest('.profile-row');
      const detailNode = row?.querySelector('.profile-detail');
      if (detailNode && result.device) {
        const parts = detailNode.textContent.split(' \u00b7 ');
        const base = parts.filter((part) => !/Android|Ch\u01b0a c\u00f3 d\u1ea5u v\u1ebft/.test(part));
        detailNode.textContent = [...base, result.device].filter(Boolean).join(' \u00b7 ');
      }
      showNotice(`Profile ${fingerprintIndex}: ${result.device}. Mở lại Chrome để áp dụng.`);
    } catch (error) {
      showNotice('Không đổi được dấu vết thiết bị.', true);
    } finally {
      fingerprintButton.disabled = false;
    }
    return;
  }
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
      : await api.openProfile(index, MAX_PROFILES,
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
    ? `Dãy ${config.stakes.length} mức · mức cược mỗi ván ${initial.toLocaleString('vi-VN')}k · giữ nguyên mức đã cấu hình, không đổi theo thắng/thua.`
    : 'Nhập ít nhất một mức cược hợp lệ.';
}

function fillBetConfig(config) {
  $('#bet-ladder-stakes').value = (config.stakes || []).join(' ');
  $('#bet-min-stake').value = config.min_t ?? 20;
  $('#bet-max-stake').value = config.max_t ?? 10000;
  $('#bet-min-profiles').value = config.min_tk ?? 2;
  $('#bet-total-target').value = config.total_bet ?? 5000;
  $('#bet-hop-rounds').value = config.hop_min ?? '2';
  $('#bet-hop-limit').value = config.hop_max ?? 5;
  $('#bet-split').value = config.split === 'odd-b' ? 'odd-b' : 'odd-p';
  $('#bet-auto-confirm').checked = config.auto_confirm !== false;
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
  if (status.error) window.aibcrAlarm?.notify?.(status.note, { level: 'error' });
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

initTheme();
window.aibcrAlarm?.init?.();

// ---------- Site configuration (CRUD) ----------
let siteRows = [];
let editingSiteId = null;

function siteChipClass(chips) {
  return chips === 'large' ? 'large' : 'small';
}

function siteChipLabel(chips) {
  return chips === 'large' ? 'Chip 100k' : 'Chip 10';
}

function renderSiteConfig(sites) {
  siteRows = Array.isArray(sites) ? sites : siteRows;
  const host = $('#site-config-list');
  if (!host) return;
  host.replaceChildren();
  if (!siteRows.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = 'Chưa có site nào. Bấm “Thêm site” để tạo.';
    host.append(empty);
    return;
  }
  siteRows.forEach((site, offset) => {
    const position = offset + 1;
    const row = document.createElement('div');
    row.className = 'site-config-row';
    row.dataset.siteId = site.id;
    row.dataset.position = String(position);
    const order = document.createElement('div');
    order.className = 'site-config-order';
    const orderBadge = document.createElement('span');
    orderBadge.className = 'site-config-order-badge';
    orderBadge.textContent = `#${position}`;
    orderBadge.title = `Vị trí ${position} trong danh sách chọn site của profile`;
    order.append(orderBadge);
    const info = document.createElement('div');
    info.className = 'site-config-info';

    const title = document.createElement('div');
    title.className = 'site-config-title';
    const name = document.createElement('strong');
    name.textContent = site.label || site.id;
    const idTag = document.createElement('span');
    idTag.className = 'site-config-id';
    idTag.textContent = site.id;
    const chip = document.createElement('span');
    chip.className = `site-config-chip ${siteChipClass(site.chips)}`;
    chip.textContent = siteChipLabel(site.chips);
    const badge = document.createElement('span');
    badge.className = site.automation ? 'site-config-auto' : 'site-config-manual';
    badge.textContent = site.automation ? 'Tự vào DG' : 'Thủ công';
    title.append(name, idTag, chip, badge);

    const url = document.createElement('span');
    url.className = 'site-config-url';
    url.textContent = site.url;
    url.title = site.url;
    info.append(title, url);

    const buttons = document.createElement('div');
    buttons.className = 'site-config-buttons';
    const toTop = document.createElement('button');
    toTop.type = 'button';
    toTop.className = 'site-move site-move-top';
    toTop.textContent = '↑ Đầu';
    toTop.title = 'Đưa site lên vị trí 1 trong danh sách chọn site';
    toTop.disabled = position === 1;
    toTop.addEventListener('click', () => reorderSite(site, 'top'));
    const up = document.createElement('button');
    up.type = 'button';
    up.className = 'site-move site-move-up';
    up.textContent = '▲';
    up.title = 'Tăng 1 vị trí';
    up.setAttribute('aria-label', `Đưa ${site.label || site.id} lên 1 vị trí`);
    up.disabled = position === 1;
    up.addEventListener('click', () => reorderSite(site, 'up'));
    const down = document.createElement('button');
    down.type = 'button';
    down.className = 'site-move site-move-down';
    down.textContent = '▼';
    down.title = 'Giảm 1 vị trí';
    down.setAttribute('aria-label', `Đưa ${site.label || site.id} xuống 1 vị trí`);
    down.disabled = position === siteRows.length;
    down.addEventListener('click', () => reorderSite(site, 'down'));
    const edit = document.createElement('button');
    edit.type = 'button';
    edit.textContent = 'Sửa';
    edit.addEventListener('click', () => openSiteForm(site));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'danger';
    remove.textContent = 'Xoá';
    remove.addEventListener('click', () => deleteSite(site));
    buttons.append(toTop, up, down, edit, remove);

    row.append(order, info, buttons);
    host.append(row);
  });
}

function setSiteFormNote(message, isError = false) {
  const note = $('#site-form-note');
  if (!note) return;
  note.textContent = message || '';
  note.dataset.state = isError ? 'error' : 'ready';
}

function openSiteForm(site = null) {
  const form = $('#site-form');
  if (!form) return;
  editingSiteId = site?.id || null;
  form.hidden = false;
  $('#site-form-id').value = site?.id || '';
  $('#site-form-id').disabled = Boolean(site);
  $('#site-form-label').value = site?.label || '';
  $('#site-form-chips').value = site?.chips === 'large' ? 'large' : 'small';
  $('#site-form-url').value = site?.url || '';
  setSiteFormNote(site ? `Đang sửa: ${site.id}` : 'Nhập thông tin site mới.');
  $('#site-form-label').focus();
}

function closeSiteForm() {
  const form = $('#site-form');
  if (form) form.hidden = true;
  editingSiteId = null;
  setSiteFormNote('');
}

async function refreshSiteRows() {
  const info = await api.info().catch(() => null);
  if (info?.profileSites) {
    profileSites = info.profileSites;
    renderSiteConfig(profileSites);
  }
}

async function saveSiteFromForm(event) {
  event.preventDefault();
  const payload = {
    id: $('#site-form-id').value.trim().toLowerCase(),
    label: $('#site-form-label').value.trim(),
    chips: $('#site-form-chips').value,
    url: $('#site-form-url').value.trim(),
  };
  const result = editingSiteId
    ? await api.updateSite({ ...payload, id: editingSiteId, originalId: editingSiteId, label: payload.label, url: payload.url, chips: payload.chips })
    : await api.createSite(payload);
  if (!result?.ok) {
    setSiteFormNote(result?.error || 'Không lưu được site.', true);
    return;
  }
  profileSites = result.sites || profileSites;
  renderSiteConfig(profileSites);
  closeSiteForm();
  syncProfileSiteOptions();
  renderProfiles(MAX_PROFILES, lastSiteLabel, [], selectedIndicesOrDefault());
  showNotice(editingSiteId ? 'Đã cập nhật site.' : 'Đã thêm site mới.');
}

async function deleteSite(site) {
  if (!window.confirm(`Xoá site "${site.label || site.id}"?`)) return;
  const result = await api.deleteSite(site.id);
  if (!result?.ok) {
    showNotice(result?.error || 'Không xoá được site.', true);
    return;
  }
  profileSites = result.sites || [];
  renderSiteConfig(profileSites);
  syncProfileSiteOptions();
  renderProfiles(MAX_PROFILES, lastSiteLabel, [], selectedIndicesOrDefault());
  showNotice(`Đã xoá site ${site.id}.`);
}

// Sắp xếp lại thứ tự site: thứ tự này chính là thứ tự option ở mọi dropdown
// chọn site của profile, và cũng là thứ tự mặc định khi mở/chạy nhóm.
async function reorderSite(site, action) {
  if (!site?.id) return;
  const result = await api.reorderSite(site.id, action);
  if (!result?.ok) {
    showNotice(result?.error || 'Không sắp xếp được site.', true);
    return;
  }
  profileSites = result.sites || profileSites;
  renderSiteConfig(profileSites);
  syncProfileSiteOptions();
  renderProfiles(MAX_PROFILES, lastSiteLabel, [], selectedIndicesOrDefault());
  showNotice(result.note || 'Đã cập nhật thứ tự site.');
}

// Keep every per-profile site dropdown in step with the editable list.
function syncProfileSiteOptions() {
  for (const select of document.querySelectorAll('.profile-site-select')) {
    const previous = select.value;
    select.replaceChildren();
    for (const site of profileSites) {
      const option = document.createElement('option');
      option.value = site.id;
      option.textContent = site.display || site.label;
      select.append(option);
    }
    if (profileSites.some((site) => site.id === previous)) {
      select.value = previous;
    } else if (profileSites[0]) {
      select.value = profileSites[0].id;
      profileSiteSelections[String(select.dataset.profile)] = profileSites[0].id;
    }
  }
}

$('#site-add')?.addEventListener('click', () => openSiteForm(null));
$('#site-form-cancel')?.addEventListener('click', closeSiteForm);
$('#site-form')?.addEventListener('submit', saveSiteFromForm);
$('#site-reset')?.addEventListener('click', async () => {
  if (!window.confirm('Khôi phục danh sách site mặc định? Các thay đổi sẽ mất.')) return;
  const result = await api.resetSites();
  if (!result?.ok) {
    showNotice(result?.error || 'Không khôi phục được.', true);
    return;
  }
  profileSites = result.sites || [];
  renderSiteConfig(profileSites);
  syncProfileSiteOptions();
  renderProfiles(MAX_PROFILES, lastSiteLabel, [], selectedIndicesOrDefault());
  showNotice(result.note || 'Đã khôi phục site mặc định.');
});


(async function boot() {
  try {
    const info = await api.info();
    profileSites = info.profileSites || [];
    renderSiteConfig(profileSites);
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
    renderProviderAssignments('omni');
    renderProviderAssignments('hidemium');
    await restoreRememberedConnections();
    syncProfilePicker();
    renderProfiles(MAX_PROFILES, lastSiteLabel, [], selectedIndicesOrDefault());
    updateSitePreview();
    setProfileSubtab(localStorage.getItem(PROFILE_SUBTAB_KEY) || (
      savedSource === 'omni' || savedSource === 'hidemium' ? savedSource : 'chrome'), { applySource: false });
    showNotice('');
  } catch (error) {
    showNotice(`Không tải được danh sách website: ${error.message || error}`, true);
  }
})();
