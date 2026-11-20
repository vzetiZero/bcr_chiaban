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

function renderSettings(count) {
  const previous = new Map();
  for (const [index, card] of settingsByIndex) {
    previous.set(index, {
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
      <label class="setting-field"><span>Rộng (px)</span><input data-setting="width" type="number" min="520" max="3840" step="1" /></label>
      <label class="setting-field"><span>Cao (px)</span><input data-setting="height" type="number" min="200" max="2160" step="1" /></label>
      <label class="setting-field"><span>Scale (%)</span><input data-setting="scale" type="number" min="50" max="200" step="1" /></label>`;
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
      proxyId: proxyAssignments[String(offset + 1)] || '',
      width: Number(card.querySelector('[data-setting="width"]').value) || 900,
      height: Number(card.querySelector('[data-setting="height"]').value) || 500,
      scale: Number(card.querySelector('[data-setting="scale"]').value) || 100,
    };
  });
}

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
  renderSettings(value);
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
      showNotice('Đang mở sảnh Dream Gaming trên các profile…');
      const dgResult = await api.openDreamGaming();
      if (!dgResult || !dgResult.ok) {
        showNotice((dgResult && dgResult.error) || 'Không mở được sảnh Dream Gaming.', true);
        return;
      }
      const dgFailed = dgResult.replies.filter((reply) => !reply.ok).length;
      if (dgFailed) {
        showNotice(`Đã chạy ${result.count} profile; ${dgFailed} profile chưa vào được sảnh DG.`, true);
        return;
      }
      showNotice('Đang đưa tất cả profile vào cùng một bàn DG…');
      const sync = await api.syncFebetTableById('');
      if (!sync || !sync.ok) {
        showNotice((sync && sync.error) || 'Các profile đã mở DG nhưng chưa đồng bộ được bàn.', true);
        return;
      }
      const syncFailed = (sync.replies || []).filter((reply) => !reply.ok);
      if (syncFailed.length) {
        const detail = syncFailed.map((reply) => `Profile ${reply.index}: ${reply.error}`).join(' · ');
        showNotice(`Bàn ${sync.table_id}: ${syncFailed.length}/${sync.count} profile lỗi. ${detail}`, true);
        return;
      }
      const lobbyOnly = (sync.replies || []).filter((reply) => reply.in_table === false);
      if (lobbyOnly.length) {
        showNotice(`${lobbyOnly.length} profile mới đứng ở lưới sảnh, chưa vào bàn thật.`, true);
        return;
      }
      showNotice(`Cả ${sync.count} profile đã vào bàn ${sync.table_id}; đang áp dụng cấu hình cược…`);
      const { amount, unit } = betStake();
      const bets = await api.applyBets(amount, unit, $('#bet-split').value);
      renderBetAssignments(bets);
      if (!bets || !bets.ok) {
        showNotice((bets && bets.error) || 'Không áp dụng được cấu hình cược.', true);
        return;
      }
      const betFailed = (bets.replies || []).filter((reply) => !reply.ok);
      showNotice(betFailed.length
        ? `Đã vào bàn ${sync.table_id}; ${betFailed.length} profile lỗi cấu hình cược.`
        : `Hoàn tất: ${result.count} profile cùng bàn ${sync.table_id},`
          + ` mỗi tay ${Number(bets.stake).toLocaleString('vi-VN')} đv, hai cửa đối lập.`,
        betFailed.length > 0);
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

function betStake() {
  const amount = Math.max(1, Math.trunc(Number($('#bet-amount').value) || 1));
  const unit = Number($('#bet-unit').value) === 10000 ? 10000 : 10;
  return { amount, unit, stake: amount * unit };
}

function updateBetPreview() {
  const { amount, unit, stake } = betStake();
  const unitLabel = unit === 10000 ? '10k' : '10';
  $('#bet-stake-preview').textContent =
    `Mỗi tay: ${amount} chip × ${unitLabel} = ${stake.toLocaleString('vi-VN')} đơn vị sảnh`
    + ` (thang WM: 1 đv = 1.000đ → ${(stake * 1000).toLocaleString('vi-VN')}đ).`
    + ' Hai nhóm profile đặt cùng số tiền này ở hai cửa đối lập.';
}

$('#bet-amount').addEventListener('input', updateBetPreview);
$('#bet-unit').addEventListener('change', updateBetPreview);
updateBetPreview();

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
    setProxyState(await api.listProxies());
    renderSettings(Math.max(1, Math.min(8, Number(profileCount.value) || 1)));
    renderProfiles(Math.max(1, Math.min(8, Number(profileCount.value) || 1)), lastSiteLabel);
    updateSitePreview();
    showNotice('');
  } catch (error) {
    showNotice(`Không tải được danh sách website: ${error.message || error}`, true);
  }
})();
