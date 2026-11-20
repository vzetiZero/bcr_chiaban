const api = window.aibcr;
const $ = (selector) => document.querySelector(selector);
const profileSelect = $('#site-select');
const profileCount = $('#profile-count');
const profileList = $('#profile-list');
const settingsList = $('#profile-settings');
const runButton = $('#run-profiles');
const notice = $('#notice');
const statusByIndex = new Map();
const settingsByIndex = new Map();

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
  if (!row) return;
  row.className = `profile-row ${state}`;
  row.querySelector('.profile-state').textContent = state === 'running' ? 'Đang chạy'
    : state === 'error' ? 'Có lỗi' : 'Đang mở';
  row.querySelector('.profile-detail').textContent = detail;
}

function renderProfiles(count, siteLabel, replies = []) {
  profileList.replaceChildren();
  statusByIndex.clear();
  $('#profile-total').textContent = `${count} profile · ${siteLabel}`;
  for (let index = 1; index <= count; index += 1) {
    const reply = replies[index - 1] || {};
    const row = document.createElement('article');
    row.className = `profile-row ${reply.ok ? 'opening' : 'error'}`;
    row.innerHTML = `<div class="profile-number">${String(index).padStart(2, '0')}</div>
      <div class="profile-info"><strong>Profile ${index}</strong><span class="profile-detail"></span></div>
      <span class="profile-state"></span>`;
    const detail = reply.note || reply.error || '';
    const proxy = reply.proxy ? ` · ${reply.proxy}` : '';
    const size = reply.width && reply.height ? ` · ${reply.width}×${reply.height} · ${reply.scale}%` : '';
    row.querySelector('.profile-detail').textContent = `${detail}${proxy}${size}`;
    row.querySelector('.profile-state').textContent = reply.ok ? 'Đang mở' : 'Có lỗi';
    profileList.append(row);
    statusByIndex.set(index, row);
  }
}

function updateSitePreview() {
  const site = profileSelect.selectedOptions[0];
  $('#site-url').textContent = site ? site.dataset.url || '' : '';
  runButton.disabled = !site || !site.value;
}

function renderSettings(count) {
  const previous = new Map();
  for (const [index, card] of settingsByIndex) {
    previous.set(index, {
      proxy: card.querySelector('[data-setting="proxy"]').value,
      width: card.querySelector('[data-setting="width"]').value,
      height: card.querySelector('[data-setting="height"]').value,
      scale: card.querySelector('[data-setting="scale"]').value,
    });
  }
  settingsByIndex.clear();
  settingsList.replaceChildren();
  for (let index = 1; index <= count; index += 1) {
    const saved = previous.get(index) || {};
    const card = document.createElement('article');
    card.className = 'settings-card';
    card.innerHTML = `<div class="settings-title"><strong>Profile ${index}</strong><span>Thiết lập riêng</span></div>
      <label class="setting-field proxy-field"><span>Proxy</span><input data-setting="proxy" type="password" autocomplete="off" spellcheck="false" placeholder="Để trống = IP trực tiếp" /></label>
      <label class="setting-field"><span>Rộng (px)</span><input data-setting="width" type="number" min="520" max="3840" step="1" /></label>
      <label class="setting-field"><span>Cao (px)</span><input data-setting="height" type="number" min="200" max="2160" step="1" /></label>
      <label class="setting-field"><span>Scale (%)</span><input data-setting="scale" type="number" min="50" max="200" step="1" /></label>`;
    card.querySelector('[data-setting="proxy"]').value = saved.proxy || '';
    card.querySelector('[data-setting="width"]').value = saved.width || '900';
    card.querySelector('[data-setting="height"]').value = saved.height || '500';
    card.querySelector('[data-setting="scale"]').value = saved.scale || '100';
    settingsList.append(card);
    settingsByIndex.set(index, card);
  }
}

function collectSettings(count) {
  return Array.from({ length: count }, (_, offset) => {
    const card = settingsByIndex.get(offset + 1);
    return {
      proxy: card.querySelector('[data-setting="proxy"]').value.trim(),
      width: Number(card.querySelector('[data-setting="width"]').value) || 900,
      height: Number(card.querySelector('[data-setting="height"]').value) || 500,
      scale: Number(card.querySelector('[data-setting="scale"]').value) || 100,
    };
  });
}

profileSelect.addEventListener('change', updateSitePreview);
$('#profile-count').addEventListener('change', () => {
  const value = Math.max(1, Math.min(8, Number(profileCount.value) || 1));
  profileCount.value = String(value);
  renderSettings(value);
});

runButton.addEventListener('click', async () => {
  const count = Math.max(1, Math.min(8, Math.trunc(Number(profileCount.value) || 1)));
  profileCount.value = String(count);
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
    showNotice(failed
      ? `Đã gửi lệnh mở ${result.count} profile; ${failed} profile báo lỗi.`
      : `Đã gửi lệnh mở đồng thời ${result.count} profile tại ${result.site}.`);
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
    for (const index of statusByIndex.keys()) updateProfile(index, 'closed', 'Đã gửi lệnh đóng cửa sổ.');
    showNotice(`Đã gửi lệnh đóng ${result.count} cửa sổ Chrome.`);
  } catch (error) {
    showNotice(String(error.message || error), true);
  }
});

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
    renderSettings(Math.max(1, Math.min(8, Number(profileCount.value) || 1)));
    updateSitePreview();
    showNotice('Chọn số lượng profile và website, sau đó bấm Chạy đồng thời.');
  } catch (error) {
    showNotice(`Không tải được danh sách website: ${error.message || error}`, true);
  }
})();
