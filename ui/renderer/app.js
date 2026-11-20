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
const profileStateByIndex = new Map();
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
  renderProfiles(value, lastSiteLabel);
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

function setFebetNote(message, isError = false) {
  const target = $('#febet-note');
  target.textContent = message;
  target.dataset.state = isError ? 'error' : 'ready';
}

$('#open-dg-all').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  setFebetNote('Đang mở Dream Gaming Baccarat trong các profile…');
  try {
    const result = await api.openDreamGaming();
    if (!result || !result.ok) {
      setFebetNote((result && result.error) || 'Không mở được DG.', true);
      return;
    }
    const opened = result.replies.filter((reply) => reply.ok).length;
    const failed = result.replies.filter((reply) => !reply.ok);
    const errors = failed.map((reply) => `Profile ${reply.index}: ${reply.error}`).join(' · ');
    setFebetNote(`Đã xử lý ${result.count} profile; ${opened} profile mở hoặc đã có iframe DG.${errors ? ` ${errors}` : ''}`, failed.length > 0);
  } catch (error) {
    setFebetNote(String(error.message || error), true);
  } finally {
    button.disabled = false;
  }
});

$('#scan-dg').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  const select = $('#dg-table-select');
  button.disabled = true;
  setFebetNote('Đang quét iframe của Profile 1…');
  try {
    const result = await api.inspectFebet();
    if (!result || !result.ok) {
      setFebetNote((result && result.error) || 'Không quét được iframe.', true);
      return;
    }
    select.replaceChildren();
    for (const optionData of result.options || []) {
      const option = document.createElement('option');
      option.value = optionData.label;
      option.textContent = optionData.origin ? `${optionData.label} · ${optionData.origin}` : optionData.label;
      select.append(option);
    }
    select.disabled = !select.options.length;
    $('#sync-dg-table').disabled = !select.options.length;
    if (!select.options.length) {
      const empty = document.createElement('option');
      empty.value = '';
      empty.textContent = 'Iframe chưa có nhãn bàn để chọn';
      select.append(empty);
      select.disabled = true;
    }
    const frameSummary = (result.frames || []).map((frame) => frame.title || frame.origin || 'iframe').join(', ');
    setFebetNote(`${result.note || ''}${frameSummary ? ` Iframe: ${frameSummary}.` : ''} Tìm thấy ${(result.options || []).length} lựa chọn.`);
  } catch (error) {
    setFebetNote(String(error.message || error), true);
  } finally {
    button.disabled = false;
  }
});

$('#dg-table-select').addEventListener('change', () => {
  $('#sync-dg-table').disabled = !$('#dg-table-select').value;
});

$('#sync-dg-table').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  const label = $('#dg-table-select').value;
  if (!label) return;
  button.disabled = true;
  setFebetNote(`Đang chọn bàn “${label}” trên các profile…`);
  try {
    const result = await api.selectFebetTable(label);
    if (!result || !result.ok) {
      setFebetNote((result && result.error) || 'Không đồng bộ được bàn.', true);
      return;
    }
    const failed = result.replies.filter((reply) => !reply.ok);
    const detail = failed.map((reply) => `Profile ${reply.index}: ${reply.error}`).join(' · ');
    setFebetNote(failed.length
      ? `Đã gửi chọn bàn tới ${result.count} profile; ${failed.length} profile chưa chọn được. ${detail}`
      : `Đã chọn “${label}” trên ${result.count} profile.`, failed.length > 0);
  } catch (error) {
    setFebetNote(String(error.message || error), true);
  } finally {
    button.disabled = !$('#dg-table-select').value;
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
    renderProfiles(Math.max(1, Math.min(8, Number(profileCount.value) || 1)), lastSiteLabel);
    updateSitePreview();
    showNotice('Chọn số lượng profile và website, sau đó bấm Chạy đồng thời.');
  } catch (error) {
    showNotice(`Không tải được danh sách website: ${error.message || error}`, true);
  }
})();
