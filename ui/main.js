// Electron main: cửa sổ + quản lý engine Python riêng cho từng trò.
// Mỗi trò = một tiến trình python riêng (profile Chrome + cổng CDP + file cấu hình riêng),
// nên thao tác ở tab này không ảnh hưởng tab kia.
const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const { randomUUID } = require('node:crypto');
const { parseProxy, proxyLabel, startProxyBridge, checkProxy } = require('./proxy_bridge');
const { commonReachableStake } = require('./chip_amounts');
const { reorderSites } = require('./site_order');
const { pickSharedTable } = require('./table_sync');

const PROJECT_ROOT = path.resolve(__dirname, '..');
const ACTIVITY_LOG_LIMIT = 5000;
let activityLogQueue = Promise.resolve();
let lastGroupLogText = '';

function activityLogPath() {
  return path.join(app.getPath('userData'), 'activity-log.json');
}

function appendActivityLog({ source = 'app', level = 'info', text = '' } = {}) {
  const safeText = String(text).replace(/((?:token|jwt|authorization|cookie|api[_-]?key)=)[^&\s]+/gi, '$1[redacted]')
    .slice(0, 2000);
  if (!safeText) return activityLogQueue;
  activityLogQueue = activityLogQueue.then(async () => {
    let rows = [];
    try {
      const parsed = JSON.parse(await fs.promises.readFile(activityLogPath(), 'utf8'));
      if (Array.isArray(parsed)) rows = parsed;
    } catch { /* nhật ký chưa được tạo */ }
    const row = { time: new Date().toISOString(), source: String(source).slice(0, 80),
      level: level === 'error' ? 'error' : 'info', text: safeText };
    rows.push(row);
    if (rows.length > ACTIVITY_LOG_LIMIT) rows = rows.slice(-ACTIVITY_LOG_LIMIT);
    await fs.promises.writeFile(activityLogPath(), JSON.stringify(rows, null, 2), 'utf8');
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('activity-log:entry', row);
  }).catch((error) => console.warn('Could not save activity log:', error.message || error));
  return activityLogQueue;
}

const PYTHON_CANDIDATES = [
  process.env.AIBCR_PYTHON,
  'python',
  path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python312', 'python.exe'),
  path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python313', 'python.exe'),
].filter(Boolean);

// Sites shipped with the app. These are seeds for the editable store below;
// the user can change links, add sites or remove them from the Config tab.
const DEFAULT_SITES = Object.freeze([
  { id: 'e3951', label: 'E3951', url: 'https://www.e3951.com/seamless?gameType=LIVE', chips: 'small', auto: true },
  { id: 'gk881', label: 'GK881', url: 'https://m.gk881.vip/', chips: 'small', auto: true },
  { id: '888ae66', label: '888AE66', url: 'https://www.888ae66.com/', chips: 'small', auto: false },
  { id: 'bum123', label: 'BUM123', url: 'https://www.bum123.com/aff/10459', chips: 'small', auto: false },
  { id: 'vnwtop', label: 'VNWTop', url: 'https://vnwtop.com/', chips: 'large', auto: true },
  { id: 'febet', label: 'FEBET Baccarat', url: 'https://febet.kiwi/live-casino/baccarat?a=c76811abcadb64fed7d82b32d7e79f3c&utm_campaign=social&utm_source=aphonso&utm_medium=sale&utm_term=bee&utm_content=KANGIN&event=', chips: 'large', auto: true },
]);

const SITE_ID_RE = /^[a-z0-9][a-z0-9_-]{1,23}$/;
const SITE_CHIPS = new Set(['small', 'large']);
let sitesCache = null;

function sitesConfigPath() {
  return path.join(app.getPath('userData'), 'sites-config.json');
}

function normalizeSite(raw) {
  const id = String(raw?.id || '').trim().toLowerCase();
  const label = String(raw?.label || '').trim().slice(0, 40);
  const url = String(raw?.url || '').trim();
  const chips = SITE_CHIPS.has(raw?.chips) ? raw.chips : 'small';
  return { id, label, url, chips, auto: Boolean(raw?.auto) };
}

function validateSite(site, existing, { allowSameId = null } = {}) {
  if (!SITE_ID_RE.test(site.id)) {
    return 'Mã site phải là 2-24 ký tự a-z, 0-9, gạch ngang hoặc gạch dưới.';
  }
  if (!site.label) return 'Tên hiển thị không được để trống.';
  let parsed;
  try { parsed = new URL(site.url); } catch { return 'Đường dẫn không hợp lệ.'; }
  if (parsed.protocol !== 'https:') return 'Đường dẫn phải bắt đầu bằng https://.';
  if (existing.some((item) => item.id === site.id && item.id !== allowSameId)) {
    return `Mã site "${site.id}" đã tồn tại.`;
  }
  return '';
}

function readSitesFromDisk() {
  try {
    const value = JSON.parse(fs.readFileSync(sitesConfigPath(), 'utf8'));
    if (Array.isArray(value?.sites) && value.sites.length) {
      return value.sites.map(normalizeSite).filter((site) => site.id && site.url);
    }
  } catch {
    // Missing or corrupt store: fall back to the shipped defaults.
  }
  return DEFAULT_SITES.map((site) => ({ ...site }));
}

// The live list used by profile opening, validation and the UI.
function sitesConfig() {
  if (!sitesCache) sitesCache = readSitesFromDisk();
  return sitesCache;
}

async function saveSitesConfig(sites) {
  const target = sitesConfigPath();
  await fs.promises.mkdir(path.dirname(target), { recursive: true });
  await fs.promises.writeFile(target, JSON.stringify({ version: 1, sites }, null, 2),
    { encoding: 'utf8' });
  sitesCache = sites;
  return sites;
}

const SITE_CHIP_LABELS = Object.freeze({
  small: 'Chip 10',
  large: 'Chip 100k',
});

function siteOptionLabel(site) {
  const chip = SITE_CHIP_LABELS[site?.chips];
  return chip ? `${site.label} · ${chip}` : site.label;
}

const DEFAULT_BET_CONFIG = Object.freeze({
  stakes: [260, 280, 300, 240, 220, 280, 320, 340, 380, 400, 360, 420,
    440, 480, 500, 420, 340, 380, 440, 280, 400, 360, 300, 340, 280,
    400, 360, 300, 280],
  min_t: 20,
  max_t: 10000,
  min_tk: 2,
  total_bet: 5000,
  hop_min: '2',
  hop_max: 5,
  split: 'odd-p',
  auto_confirm: true,
});

function betConfigPath() {
  return path.join(app.getPath('userData'), 'bet-config.json');
}

function normalizeBetConfig(value = {}) {
  const rawStakes = Array.isArray(value.stakes) ? value.stakes
    : String(value.stakes || '').split(/[\s,-]+/);
  const stakes = rawStakes.map((item) => Math.trunc(Number(item)))
    .filter((item) => Number.isFinite(item) && item > 0 && item <= 10000000);
  const min_t = Math.max(10, Math.min(10000, Math.trunc(Number(value.min_t) || 20)));
  const max_t = Math.max(min_t, Math.min(10000, Math.trunc(Number(value.max_t) || 10000)));
  const min_tk = Math.max(2, Math.min(15, Math.trunc(Number(value.min_tk) || 2)));
  const total_bet = Math.max(1, Math.min(1000000000,
    Math.trunc(Number(value.total_bet) || 5000)));
  const hopText = String(value.hop_min ?? '2').trim();
  const hopParts = hopText.split(/[\s,-]+/).filter(Boolean);
  const hop_min = hopParts.length && hopParts.every((item) => /^\d+$/.test(item)
    && Number(item) > 0) ? hopText.slice(0, 120) : '2';
  const hop_max = Math.max(1, Math.min(48, Math.trunc(Number(value.hop_max) || 5)));
  return {
    stakes: stakes.length ? stakes : [...DEFAULT_BET_CONFIG.stakes],
    min_t,
    max_t,
    min_tk,
    total_bet,
    hop_min,
    hop_max,
    split: value.split === 'odd-b' ? 'odd-b' : 'odd-p',
    // Mặc định BẬT: chỉ xếp chip mà không bấm xác nhận thì không có tay nào được
    // đặt thật. Chỉ tắt khi người dùng chủ động bỏ chọn (false), nên `undefined`
    // (cấu hình cũ chưa có trường này) cũng phải thành true.
    auto_confirm: value.auto_confirm !== false,
  };
}

async function loadBetConfig() {
  try {
    const value = JSON.parse(await fs.promises.readFile(betConfigPath(), 'utf8'));
    return normalizeBetConfig(value);
  } catch {
    return normalizeBetConfig();
  }
}

async function saveBetConfig(value) {
  const config = normalizeBetConfig(value);
  const target = betConfigPath();
  await fs.promises.mkdir(path.dirname(target), { recursive: true });
  await fs.promises.writeFile(target, JSON.stringify(config, null, 2),
    { encoding: 'utf8', mode: 0o600 });
  return config;
}

function proxyStorePath() {
  return path.join(app.getPath('userData'), 'proxy-vault.json');
}

function normalizeOmniApiUrl(value) {
  const url = new URL(String(value || 'http://127.0.0.1:35353').trim());
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '::1'].includes(url.hostname)
      || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('OmniLogin API phải là địa chỉ HTTP cục bộ, ví dụ http://127.0.0.1:35353.');
  }
  return url.origin;
}

async function omniRequest(apiUrl, pathname, timeout = 5000) {
  const base = normalizeOmniApiUrl(apiUrl);
  const response = await fetch(`${base}${pathname}`, { signal: AbortSignal.timeout(timeout) });
  const text = await response.text();
  if (!response.ok) throw new Error(`OmniLogin API trả HTTP ${response.status}.`);
  return text;
}

async function listOmniProfiles(apiUrl) {
  let payload;
  try { payload = JSON.parse(await omniRequest(apiUrl, '/profiles')); }
  catch (error) { throw new Error(`Không đọc được danh sách profile OmniLogin: ${error.message || error}`); }
  const docs = Array.isArray(payload) ? payload : payload && payload.docs;
  if (!Array.isArray(docs)) throw new Error('OmniLogin API không trả về danh sách docs hợp lệ.');
  return docs.map((doc) => ({ id: String(doc.id ?? '').trim(),
    name: String(doc.name || `Profile ${doc.id ?? ''}`).trim() }))
    .filter((doc) => doc.id && doc.id.length <= 128);
}

function omniDebugPort(profileId) {
  const value = String(profileId);
  const numericId = Number(value);
  const stable = Number.isSafeInteger(Math.abs(numericId))
    ? Math.abs(numericId)
    : [...value].reduce((hash, char) => ((hash * 31) + char.charCodeAt(0)) % 500, 1);
  return 9230 + (stable % 500);
}

async function waitForOmniDebugPort(port, timeout = 20000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const raw = await omniRequest(`http://127.0.0.1:${port}`, '/json/version', 1000);
      const version = JSON.parse(raw);
      if (typeof version.Browser === 'string' && version.Browser.includes('Chrome')) return true;
    } catch { /* profile browser is still starting */ }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

async function openOmniProfile(apiUrl, profileId) {
  const base = normalizeOmniApiUrl(apiUrl);
  const wantedPort = omniDebugPort(profileId);
  let port = wantedPort;
  let isActive = false;
  try { isActive = String(await omniRequest(base, `/active/${encodeURIComponent(profileId)}`, 1500)).trim().toLowerCase() === 'true'; }
  catch { /* Older OmniLogin builds may not expose /active; use /open below. */ }
  if (!(isActive && await waitForOmniDebugPort(port, 1000))) {
    const query = new URLSearchParams({ profile_id: String(profileId), remote_debug_port: String(wantedPort) });
    let response;
    try { response = JSON.parse(await omniRequest(base, `/open?${query}`, 15000)); }
    catch (error) { throw new Error(`Không mở được profile OmniLogin ${profileId}: ${error.message || error}`); }
    if (response.success === false || response.ok === false) {
      throw new Error(String(response.error || response.message || `OmniLogin từ chối mở profile ${profileId}.`));
    }
    const address = response.remote_debug_address || response.data?.remote_debug_address || '';
    const socket = response.web_socket_debugger_url || response.data?.web_socket_debugger_url || '';
    const addressPort = String(address).match(/:(\d+)$/);
    const socketPort = String(socket).match(/:(\d+)\//);
    port = Number((addressPort && addressPort[1]) || (socketPort && socketPort[1]) || wantedPort);
  }
  if (!(await waitForOmniDebugPort(port, 20000))) {
    throw new Error(`Profile OmniLogin ${profileId} chưa mở cổng CDP ${port} sau 20 giây.`);
  }
  return { provider: 'omni', profileId: String(profileId), port, apiUrl: base };
}

async function stopOmniProfile(profile) {
  if (!profile) return;
  const id = encodeURIComponent(String(profile.profileId));
  try {
    if (profile.provider === 'hidemium') await hidemiumRequest(profile.apiUrl, `/closeProfile?uuid=${id}`, 10000);
    else await omniRequest(profile.apiUrl, `/stop/${id}`, 5000);
  }
  catch (error) {
    // Keep the local ChromeDriver detached even if the manager is already stopped.
    console.warn(`Không xác nhận được lệnh đóng OmniLogin ${id}: ${error.message || error}`);
  }
}

function normalizeHidemiumApiUrl(value) {
  const url = new URL(String(value || 'http://127.0.0.1:5555').trim());
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '::1'].includes(url.hostname)
      || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Hidemium API phải là địa chỉ HTTP cục bộ, ví dụ http://127.0.0.1:5555.');
  }
  return url.origin;
}

async function hidemiumRequest(apiUrl, pathname, timeout = 10000, method = 'GET') {
  const base = normalizeHidemiumApiUrl(apiUrl);
  const response = await fetch(`${base}${pathname}`, { method, signal: AbortSignal.timeout(timeout) });
  const text = await response.text();
  if (!response.ok) throw new Error(`Hidemium API trả HTTP ${response.status}.`);
  try { return JSON.parse(text); } catch { return text; }
}

async function listHidemiumProfiles(apiUrl) {
  let payload = await hidemiumRequest(apiUrl, '/profileList?page=1&limit=1000');
  let content = payload?.data?.content || payload?.content || payload?.data;
  // The docs list POST as the method but show GET in their request example.
  if (!Array.isArray(content)) {
    payload = await hidemiumRequest(apiUrl, '/profileList?page=1&limit=1000', 10000, 'POST');
    content = payload?.data?.content || payload?.content || payload?.data;
  }
  if (!Array.isArray(content)) throw new Error('Hidemium API không trả về danh sách profile hợp lệ.');
  return content.map((item) => ({ id: String(item.uuid ?? item.browser_uuid ?? '').trim(),
    name: String(item.name || `Profile ${item.uuid || ''}`).trim() }))
    .filter((item) => item.id && item.id.length <= 128);
}

async function openHidemiumProfile(apiUrl, profileId) {
  const base = normalizeHidemiumApiUrl(apiUrl);
  const uuid = encodeURIComponent(String(profileId));
  const reply = await hidemiumRequest(base, `/openProfile?uuid=${uuid}`, 30000);
  const data = reply?.data || reply;
  const port = Number(data?.remote_port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`Hidemium không trả về remote_port hợp lệ cho profile ${profileId}.`);
  }
  return { provider: 'hidemium', profileId: String(profileId), port, apiUrl: base };
}

// Remember which OmniLogin/Hidemium profile belongs to each app profile so the
// next launch reconnects without asking the user to configure it again.
function omniConnectionPath() {
  return path.join(app.getPath('userData'), 'profile-connections.json');
}

async function loadOmniConnections() {
  try {
    const value = JSON.parse(await fs.promises.readFile(omniConnectionPath(), 'utf8'));
    return value && typeof value === 'object' && value.profiles && typeof value.profiles === 'object'
      ? value : { profiles: {} };
  } catch {
    return { profiles: {} };
  }
}

async function saveOmniConnections(store) {
  const target = omniConnectionPath();
  await fs.promises.mkdir(path.dirname(target), { recursive: true });
  await fs.promises.writeFile(target, JSON.stringify(store, null, 2),
    { encoding: 'utf8', mode: 0o600 });
}

async function rememberOmniConnection(index, omni, source, apiUrl) {
  if (!omni) return;
  const store = await loadOmniConnections();
  store.profiles[String(index)] = {
    provider: omni.provider, profileId: String(omni.profileId),
    apiUrl: apiUrl || omni.apiUrl, source, savedAt: new Date().toISOString(),
  };
  await saveOmniConnections(store);
}

async function forgetOmniConnection(index) {
  const store = await loadOmniConnections();
  if (!store.profiles[String(index)]) return;
  delete store.profiles[String(index)];
  await saveOmniConnections(store);
}

async function loadProxyStore() {
  try {
    const value = JSON.parse(await fs.promises.readFile(proxyStorePath(), 'utf8'));
    return {
      items: Array.isArray(value.items) ? value.items : [],
      assignments: value.assignments && typeof value.assignments === 'object' ? value.assignments : {},
    };
  } catch {
    return { items: [], assignments: {} };
  }
}

async function saveProxyStore(store) {
  const target = proxyStorePath();
  await fs.promises.mkdir(path.dirname(target), { recursive: true });
  await fs.promises.writeFile(target, JSON.stringify(store, null, 2), { encoding: 'utf8', mode: 0o600 });
}

function publicProxyItem(item) {
  let parsed;
  try { parsed = parseProxy(item.value); } catch { return null; }
  return {
    id: item.id,
    label: proxyLabel(parsed),
    status: item.status || 'unchecked',
    message: item.message || '',
    checkedAt: item.checkedAt || null,
  };
}

function proxyForProfile(row, store) {
  if (row && row.proxyId) {
    const entry = store.items.find((item) => item.id === row.proxyId);
    if (!entry) throw new Error('Proxy được gán cho profile không còn trong danh sách.');
    return parseProxy(entry.value);
  }
  // Accept the legacy one-off field from older UI builds.
  return parseProxy((row && row.proxy) || '');
}

let mainWindow = null;

class Engine {
  constructor(game, profileIndex = 1, layout = null, cdpPort = null) {
    this.game = game;
    this.profileIndex = profileIndex;
    this.layout = layout;
    this.cdpPort = cdpPort || 9222 + profileIndex - 1;
    this.child = null;
    this.buffer = '';
    this.nextId = 1;
    this.pending = new Map();
    this.ready = false;
    this.stopping = false;      // đang tắt app: không báo lỗi pipe nữa
    this.stderrTail = '';       // dòng stderr cuối, để giải thích khi engine thoát
    this.restartTimer = null;   // hẹn giờ tự khởi động lại engine đã thoát
    this.autoRestarts = 0;      // số lần tự khởi động lại liên tiếp (chống lặp vô hạn)
    this.exitExplained = false; // đã báo lý do thoát (markDead) -> đừng báo lại
  }

  send(payload) {
    const child = this.child;
    if (!child || child.killed) return false;
    // Engine đã thoát thì stdin là pipe gãy: kiểm tra trước để không phát sinh EPIPE.
    if (!child.stdin || child.stdin.destroyed || !child.stdin.writable) return false;
    try {
      child.stdin.write(JSON.stringify(payload) + '\n');
      return true;
    } catch (error) {
      this.onPipeError(error);
      return false;
    }
  }

  /** Pipe hỏng (EPIPE): engine đã thoát. Nuốt lỗi, đánh dấu chết và khởi động lại sau. */
  onPipeError(error) {
    const code = (error && error.code) || '';
    if (code === 'EPIPE' || code === 'ERR_STREAM_DESTROYED' || code === 'ERR_STREAM_WRITE_AFTER_END') {
      this.markDead(`mất kết nối engine (${code})`);
      return;
    }
    this.emitEvent('log', { level: 'error', text: `engine: ${String((error && error.message) || error)}` });
  }

  /** Dọn engine đang chết: reject lệnh đang chờ, lần gọi sau sẽ spawn lại. */
  markDead(reason) {
    const child = this.child;
    const wasStopping = this.stopping;
    this.child = null;
    this.ready = false;
    // Reject trước khi kill: kill() bắn 'exit' ngay và handler exit sẽ ghi đè lý do
    // bằng câu chung "engine đã thoát", làm mất nguyên nhân thật (EPIPE...).
    for (const [, entry] of this.pending) entry.reject(new Error(reason));
    this.pending.clear();
    this.exitExplained = true;      // 'exit' theo sau không cần báo lại lý do
    if (child) {
      try { if (!child.killed) child.kill(); } catch (error) { /* bỏ qua */ }
    }
    if (!wasStopping) {
      this.emitEvent('log', { level: 'error', text: `${reason} — sẽ tự khởi động lại.` });
    }
  }

  start() {
    if (this.child) return;
    const python = PYTHON_CANDIDATES.find((candidate) => {
      if (candidate === 'python') return true;
      return fs.existsSync(candidate);
    }) || 'python';
    this.stopping = false;
    this.stderrTail = '';
    this.buffer = '';
    const args = ['-m', 'aibcr.service.engine', '--game', 'baccarat',
      '--cdp-port', String(this.cdpPort),
      '--profile-dir', this.profileIndex === 1 ? 'chrome_profile' : `chrome_profile_${this.profileIndex}`,
      '--state', this.profileIndex === 1 ? 'aibcr_state_baccarat.json' : `aibcr_state_baccarat_${this.profileIndex}.json`];
    if (this.layout) args.push('--window-position', String(this.layout.left), String(this.layout.top),
      '--window-size', String(this.layout.width), String(this.layout.height));
    const child = spawn(python, args, {
      cwd: PROJECT_ROOT,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
      windowsHide: true,
    });
    this.child = child;

    // Thiếu các handler 'error' dưới đây thì lỗi spawn (không có python) hoặc EPIPE khi
    // engine thoát sẽ thành "Uncaught Exception" của main process — Electron bật hộp
    // thoại đỏ "A JavaScript error occurred in the main process" và app đứng.
    child.on('error', (error) => {
      const reason = `không chạy được engine (${error.code || error.message})`;
      if (this.child === child) this.markDead(reason);
      else this.emitEvent('log', { level: 'error', text: reason });
    });
    if (child.stdin) child.stdin.on('error', (error) => this.onPipeError(error));

    if (child.stdout) {
      child.stdout.setEncoding('utf8');
      child.stdout.on('data', (chunk) => this.onData(chunk));
      child.stdout.on('error', (error) => this.onPipeError(error));
    }
    if (child.stderr) {
      child.stderr.setEncoding('utf8');
      child.stderr.on('data', (chunk) => {
        const text = String(chunk).trim();
        if (text) this.stderrTail = text.slice(-300);
        this.emitEvent('log', { level: 'error', text: `engine stderr: ${text}` });
      });
      child.stderr.on('error', () => { /* chỉ là log chẩn đoán */ });
    }

    child.on('exit', (code, signal) => {
      const stopping = this.stopping;
      const explained = this.exitExplained;
      this.exitExplained = false;
      if (this.child === child) {
        this.child = null;
        this.ready = false;
      }
      for (const [, entry] of this.pending) entry.reject(new Error('engine đã thoát'));
      this.pending.clear();
      if (stopping) return;
      if (!explained) {
        const tail = this.stderrTail ? ` · ${this.stderrTail}` : '';
        this.emitEvent('log', {
          level: 'error',
          text: `engine đã thoát (${code === null ? signal : code})${tail} — lệnh kế tiếp sẽ khởi động lại.`,
        });
      }
      this.scheduleRestart();
    });
  }

  /** Tự dựng lại engine vừa thoát để UI không "đứng" mà không biết vì sao. */
  scheduleRestart() {
    if (this.stopping || this.restartTimer || this.child) return;
    if (this.autoRestarts >= 5) {
      this.autoRestarts = 0;      // thao tác kế tiếp của người dùng sẽ thử lại
      this.emitEvent('log', {
        level: 'error',
        text: 'engine thoát 5 lần liên tiếp — đã ngừng tự khởi động lại. Bấm lại thao tác để thử.',
      });
      return;
    }
    const delay = Math.min(2000 * (2 ** this.autoRestarts), 20000);
    this.autoRestarts += 1;
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (this.stopping || this.child) return;
      this.start();
    }, delay);
  }

  onData(chunk) {
    this.buffer += chunk;
    let index = this.buffer.indexOf('\n');
    while (index >= 0) {
      const line = this.buffer.slice(0, index).trim();
      this.buffer = this.buffer.slice(index + 1);
      if (line) this.onLine(line);
      index = this.buffer.indexOf('\n');
    }
  }

  onLine(line) {
    let message = null;
    try {
      message = JSON.parse(line);
    } catch (error) {
      this.emitEvent('log', { level: 'error', text: `engine: ${line.slice(0, 200)}` });
      return;
    }
    if (message.event) {
      if (message.event === 'ready') {
        this.ready = true;
        this.autoRestarts = 0;
      }
      this.emitEvent(message.event, message.data);
      return;
    }
    const entry = this.pending.get(message.id);
    if (!entry) return;
    this.pending.delete(message.id);
    if (message.ok) entry.resolve(message.result);
    else entry.reject(new Error(message.error || 'engine báo lỗi'));
  }

  emitEvent(event, data) {
    if (['log', 'opened', 'open_error', 'stopped'].includes(event)) {
      const text = event === 'log' ? data?.text : `${event}: ${typeof data === 'string' ? data : JSON.stringify(data || {})}`;
      appendActivityLog({ source: this.game, level: data?.level || (event === 'open_error' ? 'error' : 'info'), text });
    }
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('engine:event', { game: this.game, event, data });
    }
  }

  call(method, params = {}, timeout = 30000) {
    this.start();
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`hết thời gian chờ ${method}`));
      }, timeout);
      this.pending.set(id, {
        resolve: (value) => { clearTimeout(timer); resolve(value); },
        reject: (error) => { clearTimeout(timer); reject(error); },
      });
      if (!this.send({ id, method, params })) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(new Error('không gửi được lệnh tới engine'));
      }
    });
  }

  stop() {
    this.stopping = true;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    if (!this.child) return;
    this.send({ id: 0, method: 'shutdown', params: {} });
    const child = this.child;
    setTimeout(() => {
      try { if (!child.killed) child.kill(); } catch (error) { /* bỏ qua */ }
    }, 1500);
  }
}

const engines = { baccarat: new Engine('baccarat', 1) };
const activeProxyBridges = new Map();
const activeProfileIndices = new Set();
const activeOmniProfiles = new Map();
let sharedHop = null;
let groupBetting = null;
let groupBetTimer = null;
let lastGroupStatusAt = 0;

function configuredHopRounds(value) {
  const rounds = String(value || '2').trim().split(/[\s,-]+/)
    .map((part) => Number(part)).filter((number) => Number.isInteger(number) && number > 0);
  return rounds.length ? rounds : [2];
}

function sendHopStatus(payload) {
  const note = String(payload?.note || '').trim();
  if (note && note !== lastGroupLogText) {
    lastGroupLogText = note;
    appendActivityLog({ source: 'điều phối nhóm', level: payload.error ? 'error' : 'info', text: note });
  }
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('group-hop', payload);
}

function startSharedHop(tableId, tableIds, config, indices) {
  const options = Array.from(new Set((tableIds || []).map(String)
    .filter((id) => /^60\d{3,}$/.test(id))));
  if (!options.includes(String(tableId))) options.unshift(String(tableId));
  sharedHop = {
    active: true,
    tableId: String(tableId),
    tableIds: options,
    indices: [...indices],
    config: { total_bet: config.total_bet },
    schedule: configuredHopRounds(config.hop_min),
    maxHops: config.hop_max,
    rounds: 0,
    hops: 0,
    totalWagered: 0,
    since: Date.now() / 1000,
    pending: new Map(),
    counted: new Set(),
    targetNotified: false,
    busy: false,
  };
  sendHopStatus({ active: true, table_id: sharedHop.tableId, rounds: 0, hops: 0,
    note: 'Đang theo dõi số ván chung để xoay cả nhóm cùng bàn.' });
}

async function rotateSharedProfiles() {
  if (!sharedHop || !sharedHop.active || sharedHop.busy) return;
  if (sharedHop.hops >= sharedHop.maxHops) {
    sharedHop.active = false;
    sendHopStatus({ active: false, hops: sharedHop.hops,
      note: `Đã đạt giới hạn ${sharedHop.maxHops} lượt đổi bàn.` });
    return;
  }
  const currentIndex = sharedHop.tableIds.indexOf(sharedHop.tableId);
  if (sharedHop.tableIds.length < 2 || currentIndex < 0) {
    sharedHop.active = false;
    sendHopStatus({ active: false, error: true,
      note: 'Không có mã bàn kế tiếp để xoay nhóm.' });
    return;
  }
  const target = sharedHop.tableIds[(currentIndex + 1) % sharedHop.tableIds.length];
  const indices = Array.from(activeProfileIndices).sort((a, b) => a - b);
  if (indices.length !== sharedHop.indices.length
      || indices.some((index, offset) => index !== sharedHop.indices[offset])) {
    sharedHop.active = false;
    sendHopStatus({ active: false, error: true,
      note: 'Danh sách profile đã thay đổi; đã dừng xoay để tránh tách nhóm.' });
    return;
  }
  sharedHop.busy = true;
  sendHopStatus({ active: true, table_id: target, hops: sharedHop.hops,
    note: `Đủ ${sharedHop.rounds} ván; đang chuyển cả nhóm sang bàn ${target}…` });
  const results = await Promise.allSettled(indices.map((index) =>
    profileEngine(index).call('dg.syncTable', { table_id: target }, 180000)));
  const replies = results.map((result, offset) => result.status === 'fulfilled'
    ? result.value : { index: indices[offset], ok: false, error: result.reason.message });
  const successful = replies.length === indices.length
    && replies.every((reply) => reply && reply.ok && reply.in_table === true);
  sharedHop.busy = false;
  if (!successful) {
    sharedHop.active = false;
    sendHopStatus({ active: false, error: true, table_id: target,
      note: 'Không xác nhận được tất cả profile ở bàn mới; đã dừng xoay nhóm.' });
    return;
  }
  sharedHop.tableId = target;
  sharedHop.hops += 1;
  sharedHop.rounds = 0;
  if (groupBetting) {
    groupBetting.tableId = target;
    groupBetting.lastPlaced = null;
    groupBetting.roundMismatchSince = 0;
  }
  sendHopStatus({ active: true, table_id: target, hops: sharedHop.hops,
    note: `Cả ${indices.length} profile đã cùng vào bàn ${target}.` });
}

function startGroupBetting(tableId, indices, config) {
  if (groupBetTimer) clearInterval(groupBetTimer);
  lastGroupLogText = '';
  groupBetting = {
    active: true, busy: false, tableId: String(tableId), indices: [...indices],
    config, lastPlaced: null, totalWagered: 0, lastMessage: '',
    skippedRound: '', skippedCount: 0, roundMismatchSince: 0,
  };
  groupBetTimer = setInterval(() => { void groupBettingTick(); }, 450);
  sendHopStatus({ active: true, table_id: String(tableId),
    note: `Đang chờ các profile cùng bàn và cùng ván để xếp chip.` });
}

function groupStatus(note, error = false) {
  if (!groupBetting || groupBetting.lastMessage === note) return;
  groupBetting.lastMessage = note;
  sendHopStatus({ active: groupBetting.active, table_id: groupBetting.tableId,
    rounds: sharedHop?.rounds || 0, hops: sharedHop?.hops || 0,
    total_bet: groupBetting.totalWagered, error, note });
}

// Abandon the current hand only. The session stays active so the next hand is
// attempted; a hard stop is reserved for structural problems (closed profiles,
// changed table, mismatched round ids).
function skipGroupRound(roundId, note) {
  if (!groupBetting) return;
  groupBetting.skippedRound = String(roundId || '');
  groupBetting.skippedCount += 1;
  groupBetting.lastPlaced = null;
  appendActivityLog({ source: 'bỏ qua tay', level: 'error', text: note });
  groupStatus(`${note} Bỏ qua tay này và chờ tay tiếp theo (đã bỏ ${groupBetting.skippedCount} tay).`);
}

function stopGroupBetting(note, error = true) {
  if (groupBetTimer) clearInterval(groupBetTimer);
  groupBetTimer = null;
  if (groupBetting) groupBetting.active = false;
  if (sharedHop) sharedHop.active = false;
  groupStatus(note, error);
}

// Đếm một ván ĐÃ ĐẶT khi bàn đã sang mã ván kế.
//
// Không đọc kết quả thắng/thua và không đổi mức cược: ván chỉ cần được xếp chip
// xong là tính một vòng, rồi nhóm xoay bàn theo lịch đã cấu hình.
async function countPlacedRound(placed) {
  if (!placed || placed.counted) return false;
  placed.counted = true;
  groupBetting.totalWagered += placed.stakes.reduce((sum, stake) => sum + stake, 0);
  if (sharedHop?.active) {
    sharedHop.rounds += 1;
    const threshold = sharedHop.schedule[sharedHop.hops % sharedHop.schedule.length];
    groupStatus(`Đã đặt xong ván ${placed.roundId} · ${sharedHop.rounds}/${threshold} ván · tổng cược ${groupBetting.totalWagered}k.`);
    if (sharedHop.config.total_bet > 0 && !sharedHop.targetNotified
        && groupBetting.totalWagered >= sharedHop.config.total_bet) {
      sharedHop.targetNotified = true;
      groupStatus(`Đã đạt mốc tổng cược ${groupBetting.totalWagered}/${sharedHop.config.total_bet}k.`);
    }
    if (sharedHop.rounds >= threshold) await rotateSharedProfiles();
  } else {
    groupStatus(`Đã đặt xong ván ${placed.roundId}.`);
  }
  return true;
}

async function groupBettingTick() {
  if (!groupBetting?.active || groupBetting.busy) return;
  const currentIndices = Array.from(activeProfileIndices).sort((a, b) => a - b);
  if (currentIndices.length !== groupBetting.indices.length
      || currentIndices.some((index, offset) => index !== groupBetting.indices[offset])) {
    stopGroupBetting('Danh sách profile đã đổi; dừng để tránh tách nhóm.', true);
    return;
  }
  groupBetting.busy = true;
  try {
    const results = await Promise.allSettled(groupBetting.indices.map((index) =>
      profileEngine(index).call('dg.betState', {}, 10000)));
    const states = results.map((result) => result.status === 'fulfilled' ? result.value : null);
    const ready = states.length === groupBetting.indices.length
      && states.every((state) => state?.ok && state.in_table === true
        && String(state.table_id) === groupBetting.tableId && state.round_id);
    if (!ready) {
      const detail = states.map((state, offset) => {
        const index = groupBetting.indices[offset];
        if (!state) return `P${index}: không trả lời`;
        if (!state.ok) return `P${index}: ${state.error || 'chưa sẵn sàng'}`;
        if (state.in_table !== true) return `P${index}: chưa vào bàn`;
        if (String(state.table_id) !== groupBetting.tableId) {
          return `P${index}: đang ở bàn ${state.table_id || '?'} (nhóm ${groupBetting.tableId})`;
        }
        return `P${index}: chưa đọc được mã ván`;
      }).join(' · ');
      groupStatus(`Chờ tất cả profile tải xong trạng thái bàn DG. ${detail}`);
      return;
    }
    const roundIds = new Set(states.map((state) => String(state.round_id)));
    if (roundIds.size !== 1) {
      // Cùng một bàn DG nhưng khác mã ván: thường chỉ là một profile đọc đúng lúc
      // bàn vừa sang ván. Không xếp chip, chờ ván kế để cả nhóm khớp lại. Nếu lệch
      // kéo dài thì hai sảnh đang phục vụ hai bàn khác nhau dù trùng mã, phải dừng
      // và báo rõ thay vì im lặng chờ.
      groupBetting.roundMismatchSince ||= Date.now();
      if (Date.now() - groupBetting.roundMismatchSince > 20000) {
        stopGroupBetting(`Mã ván lệch nhau quá lâu (${[...roundIds].join(' / ')}) `
          + `dù cùng bàn ${groupBetting.tableId}; đã dừng nhóm để không cược lệch phiên.`, true);
        return;
      }
      groupStatus(`Các profile chưa đồng bộ cùng mã ván (${[...roundIds].join(' / ')}); chưa đặt chip.`);
      return;
    }
    groupBetting.roundMismatchSince = 0;

    const roundId = String(states[0].round_id);
    if (groupBetting.skippedRound && groupBetting.skippedRound === roundId) {
      groupStatus(`Tay ${roundId} đã bỏ qua; chờ ván kế tiếp.`);
      return;
    }
    groupBetting.skippedRound = '';
    if (groupBetting.lastPlaced && groupBetting.lastPlaced.roundId !== roundId
        && !groupBetting.lastPlaced.counted) {
      const prior = groupBetting.lastPlaced;
      const confirmFlags = states.map((state, offset) =>
        Number(state.confirmed?.[prior.sides[offset]] || 0) >= prior.stakes[offset]);
      if (confirmFlags.some(Boolean) && !confirmFlags.every(Boolean)) {
        prior.partialSince ||= Date.now();
        if (Date.now() - prior.partialSince < 2000) return;
        stopGroupBetting('Chỉ một phần profile xác nhận cược thật; đã dừng nhóm để không lệch tài khoản.', true);
        return;
      }
      prior.partialSince = 0;
      await countPlacedRound(prior);
      if (!groupBetting.active || sharedHop?.busy
          || groupBetting.tableId !== String(states[0].table_id)) return;
    }
    const placed = groupBetting.lastPlaced;
    if (placed && placed.roundId === roundId) {
      const confirmationFlags = states.map((state, offset) =>
        Number(state.confirmed?.[placed.sides[offset]] || 0) >= placed.stakes[offset]);
      if (confirmationFlags.some(Boolean) && !confirmationFlags.every(Boolean)) {
        placed.partialSince ||= Date.now();
        if (Date.now() - placed.partialSince < 2000) return;
        stopGroupBetting('Chỉ một phần profile xác nhận cược thật; đã dừng nhóm để không lệch tài khoản.', true);
        return;
      }
      placed.partialSince = 0;
      placed.confirmed = confirmationFlags.every(Boolean);
      return;
    }
    if (!states.every((state) => state.bet_open)) {
      groupStatus('Đang đợi cửa cược DG mở đủ lâu trên mọi profile.');
      return;
    }
    const sides = groupBetting.indices.map((index) => {
      const oddSide = groupBetting.config.split === 'odd-b' ? 'B' : 'P';
      return index % 2 === 1 ? oddSide : (oddSide === 'P' ? 'B' : 'P');
    });
    const engineStates = await Promise.all(groupBetting.indices.map((index) =>
      profileEngine(index).call('state', {}, 10000)));
    const ladderStakes = engineStates.map((state) => Math.trunc(Number(state?.bet_ladder?.stake) || 0));
    if (ladderStakes.some((stake) => !Number.isInteger(stake) || stake <= 0)) {
      stopGroupBetting('Không đọc được mức dãy cược hiện tại của mọi profile.', true);
      return;
    }
    const targetStake = Math.min(...ladderStakes);
    const commonStake = commonReachableStake(targetStake, states);
    if (!commonStake) {
      const diagnostics = states.map((state, offset) => {
        const index = groupBetting.indices[offset];
        if (!state?.ok) return `P${index}: không đọc được trạng thái chip (${state?.error || 'chưa sẵn sàng'})`;
        return `P${index}: scale=${state.scale ?? '?'}, floor_src=${state.floor_source || '?'}, raw_min=${state.raw_min ?? '?'}, screen_min=${state.screen_floor ?? '?'}, table_min=${state.min_k ?? '?'}k, table_max=${state.max_k || '?'}k, balance=${state.balance_known ? `${state.balance_k ?? '?'}k` : 'chưa đọc được'}, chips=[${(state.denominations_k || []).join(',')}]`;
      }).join(' · ');
      appendActivityLog({ source: 'kiểm tra chip', level: 'error',
        text: `Không tìm thấy mức chung không vượt ${targetStake}k. ${diagnostics}` });
      skipGroupRound(roundId,
        `Không có mức chip chung hợp lệ không vượt ${targetStake}k.`);
      return;
    }
    const stakes = engineStates.map(() => commonStake);
    const stakeNote = commonStake < targetStake
      ? ` (d\u00e3y ${targetStake}k \u2192 ${commonStake}k theo chip chung)` : '';
    groupStatus(`Đang xếp chip ${stakes.join('/')}k vào các cửa ${sides.join('/')}…${stakeNote}`);
    const placements = await Promise.allSettled(groupBetting.indices.map((index, offset) =>
      profileEngine(index).call('dg.stageBet', {
        side: sides[offset], amount_k: stakes[offset], round_id: roundId,
        confirm: groupBetting.config.auto_confirm,
      }, 30000)));
    const replies = placements.map((entry) => entry.status === 'fulfilled' ? entry.value
      : { ok: false, error: entry.reason?.message || 'Lỗi gửi chip.' });
    if (!replies.every((reply) => reply?.ok && reply.staged)) {
      const details = replies.map((reply, i) => reply?.ok
        ? `P${groupBetting.indices[i]}: ${reply.amount_k}k ${reply.side}`
        : `P${groupBetting.indices[i]}: ${reply?.error || 'không xếp được chip'}`
          + (Number.isFinite(Number(reply?.staged_k)) ? ` (đã xác nhận ${Number(reply.staged_k)}k)` : '')).join(' · ');
      skipGroupRound(roundId, `Không xếp đủ chip cho cả nhóm: ${details}.`);
      return;
    }
    groupBetting.lastPlaced = { roundId, indices: [...groupBetting.indices], sides, stakes,
      confirmed: replies.every((reply) => reply.confirmed === true), counted: false };
    groupStatus(replies.every((reply) => reply.confirmed)
      ? `Đã xếp và xác nhận chip cho ${replies.length} profile ở ván ${roundId}.`
      : `Đã xếp chip cho ${replies.length} profile ở ván ${roundId}; chờ xác nhận trên từng bàn.`);
  } catch (error) {
    groupStatus(`Đang chờ dữ liệu cược: ${error.message || error}.`);
  } finally {
    if (groupBetting) groupBetting.busy = false;
  }
}

function profileEngine(index) {
  return engines[index === 1 ? 'baccarat' : `baccarat-profile-${index}`];
}

function ensureProfileEngine(index, layout = null, cdpPort = null) {
  const game = index === 1 ? 'baccarat' : `baccarat-profile-${index}`;
  if (!engines[game]) engines[game] = new Engine(game, index, layout, cdpPort);
  const engine = engines[game];
  engine.layout = layout || engine.layout;
  engine.cdpPort = cdpPort || 9222 + index - 1;
  return engine;
}

function proxyServerUrl(proxy) {
  if (!proxy) return '';
  const host = proxy.host.includes(':') ? `[${proxy.host}]` : proxy.host;
  return `${proxy.protocol}://${host}:${proxy.port}`;
}

async function closeProfileBridge(index) {
  const bridge = activeProxyBridges.get(index);
  activeProxyBridges.delete(index);
  if (bridge) await bridge.close().catch(() => {});
}

function tileProfileLayouts(settings, area) {
  const count = settings.length;
  const gap = 12;
  const visual = settings.map((item) => ({
    width: Math.max(1, Math.round(item.width * item.scale / 100)),
    height: Math.max(1, Math.round(item.height * item.scale / 100)),
  }));
  let columns = 1;
  let columnWidths = [];
  for (let candidate = count; candidate >= 1; candidate -= 1) {
    const widths = Array(candidate).fill(0);
    visual.forEach((size, index) => {
      const column = index % candidate;
      widths[column] = Math.max(widths[column], size.width);
    });
    const gridWidth = widths.reduce((sum, width) => sum + width, 0) + gap * (candidate - 1);
    // Keep a full row when it is only slightly wider than the desktop. Chrome's
    // visible bounds can be smaller than the configured viewport at reduced scale.
    if (gridWidth <= area.width * 1.15 || candidate === 1) {
      columns = candidate;
      columnWidths = widths;
      break;
    }
  }
  const rows = Math.ceil(count / columns);
  const rowHeights = Array(rows).fill(0);
  visual.forEach((size, index) => {
    const row = Math.floor(index / columns);
    rowHeights[row] = Math.max(rowHeights[row], size.height);
  });
  const gridWidth = columnWidths.reduce((sum, width) => sum + width, 0) + gap * (columns - 1);
  const gridHeight = rowHeights.reduce((sum, height) => sum + height, 0) + gap * (rows - 1);
  const startX = gridWidth <= area.width ? Math.floor((area.width - gridWidth) / 2) : 0;
  const startY = Math.max(0, Math.floor((area.height - gridHeight) / 2));
  const horizontalFit = gridWidth > area.width ? area.width / gridWidth : 1;
  return settings.map((item, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    const naturalLeft = columnWidths.slice(0, column).reduce((sum, width) => sum + width + gap, 0);
    const left = startX + Math.floor(naturalLeft * horizontalFit);
    const top = startY + rowHeights.slice(0, row).reduce((sum, height) => sum + height + gap, 0);
    return { ...item, left, top };
  });
}

function profileLayout(index, count, width, height, scale, area) {
  return tileProfileLayouts(Array.from({ length: count }, () => ({ width, height, scale })), area)[index - 1];
}

ipcMain.handle('profile:open', async (_event, { index, count, profile, url, source = 'local', omniApiUrl, hidemiumApiUrl }) => {
  const profileIndex = Math.trunc(Number(index));
  if (!Number.isInteger(profileIndex) || profileIndex < 1 || profileIndex > 8) {
    return { ok: false, error: 'Profile không hợp lệ.' };
  }
  if (!['local', 'omni', 'hidemium'].includes(source)) return { ok: false, error: 'Nguồn profile không hợp lệ.' };
  if (!sitesConfig().some((site) => site.url === url)) {
    return { ok: false, error: 'Hãy chọn một website hợp lệ trước khi mở profile.' };
  }
  const row = profile || {};
  const width = Math.max(520, Math.min(3840, Math.round(Number(row.width) || 900)));
  const height = Math.max(200, Math.min(2160, Math.round(Number(row.height) || 1200)));
  const scale = Math.max(50, Math.min(200, Math.round(Number(row.scale) || 60)));
  let proxy;
  let newBridge = null;
  let omni = null;
  try {
    const proxyStore = await loadProxyStore();
    if (source === 'omni' || source === 'hidemium') {
      const provider = source;
      const profileId = String((provider === 'omni' ? row.omniProfileId : row.hidemiumProfileId) || '').trim();
      if (!profileId) return { ok: false, error: `Chưa gán profile ${provider === 'omni' ? 'OmniLogin' : 'Hidemium'} cho Profile ${profileIndex}.` };
      if (row.proxyId || row.proxy || proxyStore.assignments[String(profileIndex)]) {
        return { ok: false, error: `Proxy của profile ${provider === 'omni' ? 'OmniLogin' : 'Hidemium'} cần được cấu hình trong ${provider === 'omni' ? 'OmniLogin' : 'Hidemium'}.` };
      }
      const apiUrl = provider === 'omni' ? normalizeOmniApiUrl(omniApiUrl) : normalizeHidemiumApiUrl(hidemiumApiUrl);
      const available = provider === 'omni' ? await listOmniProfiles(apiUrl) : await listHidemiumProfiles(apiUrl);
      if (!available.some((item) => item.id === profileId)) {
        return { ok: false, error: `Không tìm thấy profile ${provider === 'omni' ? 'OmniLogin' : 'Hidemium'} ${profileId} trong danh sách hiện tại.` };
      }
      const port = provider === 'omni' ? omniDebugPort(profileId) : 0;
      for (const [otherIndex, other] of activeOmniProfiles) {
        if (otherIndex !== profileIndex && other.provider === provider && (other.profileId === profileId
            || (port && omniDebugPort(other.profileId) === port))) {
          return { ok: false, error: `Profile ${provider === 'omni' ? 'OmniLogin' : 'Hidemium'} này đang được gán cho một cửa sổ khác.` };
        }
      }
      const oldOmni = activeOmniProfiles.get(profileIndex);
      if (oldOmni && (oldOmni.profileId !== profileId || oldOmni.provider !== provider)) await stopOmniProfile(oldOmni);
      omni = provider === 'omni' ? await openOmniProfile(apiUrl, profileId) : await openHidemiumProfile(apiUrl, profileId);
    } else {
      const oldOmni = activeOmniProfiles.get(profileIndex);
      if (oldOmni) await stopOmniProfile(oldOmni);
      proxy = proxyForProfile({ ...row, proxyId: row.proxyId || proxyStore.assignments[String(profileIndex)] }, proxyStore);
    }
    let proxyServer = proxyServerUrl(proxy);
    if (proxy && proxy.username) {
      newBridge = await startProxyBridge(proxy);
      proxyServer = newBridge.url;
    }
    const { screen } = require('electron');
    const layout = profileLayout(profileIndex, Math.max(1, Math.min(8, Number(count) || profileIndex)),
      width, height, scale, screen.getPrimaryDisplay().workAreaSize);
    const engine = ensureProfileEngine(profileIndex, layout, omni ? omni.port : null);
    const configured = await engine.call('profile.configure', {
      url, proxy_server: proxyServer, width, height, scale, left: layout.left, top: layout.top,
      cdp_port: engine.cdpPort,
    });
    if (!configured || !configured.ok) {
      if (newBridge) await newBridge.close().catch(() => {});
      if (omni) await stopOmniProfile(omni);
      return { ok: false, error: (configured && configured.error) || 'Không áp dụng được cấu hình profile.' };
    }
    await closeProfileBridge(profileIndex);
    const opened = omni
      ? await engine.call('chrome.attachExternal', { port: omni.port, width, height, provider: omni.provider }, 45000)
      : await engine.call('chrome.open');
    if (!opened || !opened.ok) {
      if (newBridge) await newBridge.close().catch(() => {});
      if (omni) await stopOmniProfile(omni);
      activeProfileIndices.delete(profileIndex);
      return { ok: false, error: (opened && opened.error) || 'Không mở được Chrome.' };
    }
    if (omni) {
      const navigated = await engine.call('site.open', { url }, 45000);
      if (!navigated || !navigated.ok) {
        // Chrome belongs to OmniLogin. Stopping the profile here makes OmniLogin
        // kill the browser window the user just watched open, so keep it alive
        // and only report the navigation problem.
        activeOmniProfiles.set(profileIndex, omni);
        activeProfileIndices.add(profileIndex);
        return { ok: false, keepProfile: true,
          error: navigated?.error || 'Không mở được website trong profile.',
          proxy: `Proxy theo cài đặt của ${omni.provider === 'omni' ? 'OmniLogin' : 'Hidemium'}` };
      }
    }
    if (omni) {
      activeOmniProfiles.set(profileIndex, omni);
      await rememberOmniConnection(profileIndex, omni, omni.provider, omni.apiUrl)
        .catch(() => {});
    } else {
      activeOmniProfiles.delete(profileIndex);
      await forgetOmniConnection(profileIndex).catch(() => {});
    }
    if (newBridge) activeProxyBridges.set(profileIndex, newBridge);
    activeProfileIndices.add(profileIndex);
    return { ok: true, note: omni ? `Đã mở profile ${omni.provider === 'omni' ? 'OmniLogin' : 'Hidemium'} ${omni.profileId}.` : 'Đang mở Chrome profile.',
      proxy: omni ? `Proxy theo cấu hình ${omni.provider === 'omni' ? 'OmniLogin' : 'Hidemium'}` : proxyLabel(proxy), width, height, scale };
  } catch (error) {
    if (newBridge) await newBridge.close().catch(() => {});
    if (omni) await stopOmniProfile(omni);
    return { ok: false, error: error.message || 'Không mở được Chrome profile.' };
  }
});

ipcMain.handle('febet:open-dg', async (_event) => {
  const indices = Array.from(activeProfileIndices).sort((a, b) => a - b);
  if (!indices.length) return { ok: false, error: 'Hãy mở profile trước.' };
  const results = await Promise.allSettled(indices.map((index) =>
    profileEngine(index).call('dg.table', { wait: 0 }, 10000)));
  const replies = results.map((result, offset) =>
    result.status === 'fulfilled' ? { index: indices[offset], ...result.value }
      : { index: indices[offset], ok: false, error: result.reason.message });
  return { ok: true, count: indices.length, replies };
});

async function runDGGroup(count, siteIds, requestedIndices = null) {
  const wanted = Array.isArray(requestedIndices) && requestedIndices.length
    ? [...new Set(requestedIndices.map((value) => Math.trunc(Number(value)))
      .filter((value) => Number.isInteger(value) && value >= 1 && value <= 8))].sort((a, b) => a - b)
    : Array.from({ length: Math.max(1, Math.min(8, Math.trunc(Number(count) || 1))) }, (_, i) => i + 1);
  const indices = Array.from(activeProfileIndices).sort((a, b) => a - b);
  if (!indices.length) return { ok: false, error: 'Hãy mở profile trước, tự vào site và mở sảnh DG rồi mới chạy đồng bộ nhóm.' };
  const missing = wanted.filter((index) => !activeProfileIndices.has(index));
  if (missing.length) {
    return { ok: false, error: `Profile ${missing.join(', ')} chưa mở. Hãy mở đúng các profile đã chọn trước khi chạy.` };
  }
  const indicesToUse = wanted;
  const config = await loadBetConfig();
  if (indicesToUse.length < config.min_tk) {
    return { ok: false, error: `C\u1ea5u h\u00ecnh y\u00eau c\u1ea7u t\u1ed1i thi\u1ec3u ${config.min_tk} profile; hi\u1ec7n c\u00f3 ${indicesToUse.length}.` };
  }
  const sites = sitesConfig();
  const selectedSites = Array.isArray(siteIds) ? siteIds.map((id) => String(id || ''))
    : indicesToUse.map(() => sites[0]?.id || 'febet');
  if (selectedSites.length !== indicesToUse.length
      || selectedSites.some((id) => !sites.some((site) => site.id === id))) {
    return { ok: false, error: 'Mỗi profile cần có một site hợp lệ trước khi vào sảnh DG.' };
  }
  const siteFor = (index) => selectedSites[indicesToUse.indexOf(index)];
  const siteMeta = (index) => sites.find((site) => site.id === siteFor(index));
  const autoEntryIndices = indicesToUse.filter((index) => {
    const meta = siteMeta(index);
    // Only sites with a registered entry adapter can be automated.
    return meta?.auto && ['febet', 'gk881', 'e3951', 'vnwtop'].includes(meta.id);
  });
  const autoEntryStates = new Map();
  const runSiteEntry = (index) => {
    const siteId = siteFor(index);
    if (siteId === 'febet') return profileEngine(index).call('febet.openDG', {}, 360000);
    if (siteId === 'e3951') return profileEngine(index).call('e3951.openDG', { wait: 150 }, 360000);
    if (siteId === 'vnwtop') return profileEngine(index).call('vnwtop.openDG', { wait: 150 }, 360000);
    return profileEngine(index).call('gk881.openDG', { wait: 120 }, 360000);
  };
  const rememberSiteEntryResults = (entryIndices, results) => {
    results.forEach((result, offset) => {
      const index = entryIndices[offset];
      const siteId = siteFor(index);
      const siteLabel = sites.find((site) => site.id === siteId)?.label || siteId;
      const reply = result.status === 'fulfilled' ? result.value : { ok: false, error: result.reason.message };
      autoEntryStates.set(index, reply?.ok
        ? { ready: true, note: reply.note || `\u0110\u00e3 chuy\u1ec3n Profile ${index} (${siteLabel}) v\u00e0o s\u1ea3nh DG.` }
        : { ready: false, note: `${siteLabel} ch\u01b0a t\u1ef1 m\u1edf \u0111\u01b0\u1ee3c DG (${reply?.error || 'ch\u01b0a x\u00e1c nh\u1eadn'}).` });
    });
  };
  if (autoEntryIndices.length) {
    const labels = autoEntryIndices.map((index) => `Profile ${index} (${siteMeta(index)?.label || siteFor(index)})`).join(', ');
    sendHopStatus({ active: true, waiting_indices: [...indices],
      note: `\u0110ang t\u1ef1 v\u00e0o s\u1ea3nh DG cho ${labels}; c\u00e1c profile site kh\u00e1c v\u00e0o s\u1ea3nh th\u1ee7 c\u00f4ng.` });
    const autoResults = await Promise.allSettled(autoEntryIndices.map(runSiteEntry));
    rememberSiteEntryResults(autoEntryIndices, autoResults);
    const outcome = autoEntryIndices.map((index) => `P${index}: ${autoEntryStates.get(index)?.note}`)
      .join(' \u00b7 ');
    sendHopStatus({ active: true, waiting_indices: [...indices],
      profile_states: indices.map((index) => ({ index, ready: autoEntryStates.get(index)?.ready || false,
        note: autoEntryStates.get(index)?.note || 'Profile site n\u00e0y c\u1ea7n v\u00e0o s\u1ea3nh DG th\u1ee7 c\u00f4ng.' })),
      note: `K\u1ebft qu\u1ea3 t\u1ef1 v\u00e0o s\u1ea3nh DG: ${outcome}` });
  }
  sendHopStatus({ active: true,
    note: autoEntryIndices.length
      ? 'C\u00e1c profile FEBET/GK881 \u0111ang/\u0111\u00e3 t\u1ef1 v\u00e0o DG; h\u00e3y t\u1ef1 v\u00e0o s\u1ea3nh tr\u00ean c\u00e1c profile site kh\u00e1c. \u1ee8ng d\u1ee5ng qu\u00e9t m\u1ed7i 5 gi\u00e2y.'
      : 'C\u00e1c site \u0111\u00e3 m\u1edf. H\u00e3y t\u1ef1 v\u00e0o s\u1ea3nh DG tr\u00ean t\u1eebng profile; \u1ee9ng d\u1ee5ng s\u1ebd qu\u00e9t tr\u1ea1ng th\u00e1i m\u1ed7i 5 gi\u00e2y.',
    waiting_indices: [...indices] });
  let profileStates = [];
  while (indices.every((index) => activeProfileIndices.has(index))) {
    const checks = await Promise.allSettled(indices.map((index) =>
      profileEngine(index).call('dg.table', { wait: 0 }, 10000)));
    profileStates = checks.map((check, offset) => {
      const index = indices[offset];
      const result = check.status === 'fulfilled' ? check.value : null;
      // `dg.table` succeeds only after it found the DG tab/frame. A lobby may
      // not expose Laya's `enterMC` node or a table id yet, so `ok` is the
      // reliable signal that the profile reached the DG document.
      const ready = Boolean(result?.ok);
      const entryState = autoEntryStates.get(index);
      return { index, ready, in_table: result?.in_table === true,
        note: ready ? (result.in_table ? `\u0110ang \u1edf b\u00e0n ${result.table_id || ''}.` : `\u0110\u00e3 nh\u1eadn di\u1ec7n s\u1ea3nh DG.`)
          : (entryState?.ready
            ? `Lu\u1ed3ng ${siteFor(index)} \u0111\u00e3 k\u1ebft th\u00fac nh\u01b0ng ch\u01b0a x\u00e1c nh\u1eadn DG${result?.error ? ` \u00b7 ${result.error}` : ''}.`
            : (entryState?.note || `\u0110ang ch\u1edd s\u1ea3nh DG${result?.error ? ` \u00b7 ${result.error}` : ''}.`)) };
    });
    const waiting = profileStates.filter((item) => !item.ready).map((item) => item.index);
    if (!waiting.length) break;
    const waitingDetails = profileStates.filter((profile) => !profile.ready)
      .map((profile) => `P${profile.index}: ${profile.note}`).join(' \u00b7 ');
    for (let countdown = 5; countdown >= 0; countdown -= 1) {
      sendHopStatus({ active: true, countdown, waiting_indices: waiting, profile_states: profileStates,
        note: countdown === 0 ? `Đang quét lại sảnh DG cho profile ${waiting.join(', ')}...`
          : `Profile ${waiting.join(', ')} chưa vào sảnh DG; quét lại sau ${countdown} giây. ${waitingDetails}` });
      if (countdown > 0) await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    const retryIndices = waiting.filter((index) => autoEntryIndices.includes(index));
    if (retryIndices.length) {
      sendHopStatus({ active: true, waiting_indices: retryIndices,
        profile_states: profileStates,
        note: `T\u1ef1 th\u1eed l\u1ea1i lu\u1ed3ng v\u00e0o s\u1ea3nh cho ${retryIndices.map((index) => `Profile ${index}`).join(', ')}.` });
      const retryResults = await Promise.allSettled(retryIndices.map(runSiteEntry));
      rememberSiteEntryResults(retryIndices, retryResults);
      const retryOutcome = retryIndices.map((index) => `P${index}: ${autoEntryStates.get(index)?.note}`)
        .join(' \u00b7 ');
      sendHopStatus({ active: true, waiting_indices: retryIndices,
        profile_states: profileStates.map((profile) => ({ ...profile,
          note: autoEntryStates.get(profile.index)?.note || profile.note })),
        note: `K\u1ebft qu\u1ea3 th\u1eed l\u1ea1i: ${retryOutcome}` });
    }
  }
  if (!indices.every((index) => activeProfileIndices.has(index))) {
    const error = 'Đã dừng chờ sảnh vì một hoặc nhiều profile đã được đóng.';
    sendHopStatus({ active: false, error: true, note: error });
    return { ok: false, cancelled: true, error, profile_states: profileStates };
  }
  sendHopStatus({ active: true, profile_states: profileStates,
    note: 'Đã thấy sảnh DG trên tất cả profile; đang đọc danh sách bàn của từng sảnh để chọn bàn chung...' });
  // Nguyên tắc: các profile có thể vào từ site khác nhau, nhưng phải vào **cùng
  // một bàn DG**. Mã bàn 60xxx là không gian chung của DG, nên bàn hợp lệ là bàn
  // xuất hiện trong danh sách của **mọi** sảnh — không phải bàn của profile dẫn
  // đầu. Lấy bàn của leader rồi ép các profile khác vào sẽ tách nhóm khi hai site
  // hiển thị tập bàn khác nhau.
  let picked = null;
  let scanErrors = [];
  while (indices.every((index) => activeProfileIndices.has(index))) {
    const scans = await Promise.allSettled(indices.map((index) =>
      profileEngine(index).call('dg.tables', { wait: 0 }, 10000)));
    const perProfile = scans.map((result) => {
      if (result.status !== 'fulfilled') return [];
      const tables = result.value?.tables;
      return Array.isArray(tables) ? tables : [];
    });
    scanErrors = scans
      .map((result, offset) => (result.status !== 'fulfilled'
        ? `P${indices[offset]}: ${result.reason?.message || 'lỗi đọc sảnh'}`
        : (result.value?.ok ? '' : `P${indices[offset]}: ${result.value?.error || 'chưa đọc được sảnh'}`)))
      .filter(Boolean);
    picked = pickSharedTable(perProfile);
    if (picked.ok) break;
    for (let countdown = 5; countdown >= 0; countdown -= 1) {
      sendHopStatus({ active: true, countdown, profile_states: profileStates,
        note: countdown === 0 ? 'Đang quét lại danh sách bàn của tất cả sảnh DG...'
          : `Chưa chọn được bàn chung · quét lại sau ${countdown} giây.` });
      if (countdown > 0) await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
  if (!indices.every((index) => activeProfileIndices.has(index))) {
    const error = 'Đã dừng quét bàn vì một hoặc nhiều profile đã được đóng.';
    sendHopStatus({ active: false, error: true, note: error });
    return { ok: false, cancelled: true, error, profile_states: profileStates };
  }
  if (!picked?.ok) {
    const reason = picked?.error
      || scanErrors[0]
      || 'Hết thời gian chờ, chưa đọc được danh sách bàn thật từ sảnh DG.';
    sendHopStatus({ active: false, error: true, note: reason });
    return { ok: false, error: reason, scans: scanErrors };
  }
  const tableId = String(picked.table_id);
  sendHopStatus({ active: true, table_id: tableId,
    note: `Bàn chung của ${indices.length} sảnh: ${picked.table_name} (${tableId}); đang đồng bộ cả nhóm...` });
  const syncResults = await Promise.allSettled(indices.map((index) =>
    profileEngine(index).call('dg.syncTable', { table_id: tableId }, 180000)));
  const syncReplies = syncResults.map((result, offset) => result.status === 'fulfilled'
    ? { index: indices[offset], ...result.value }
    : { index: indices[offset], ok: false, error: result.reason.message });
  const notReady = syncReplies.filter((reply) => !reply.ok || reply.in_table !== true
    || String(reply.table_id || tableId) !== tableId);
  if (notReady.length) {
    const error = `${notReady.length}/${indices.length} profile chưa xác nhận vào bàn ${tableId}; đã dừng trước khi xếp chip.`;
    sendHopStatus({ active: false, error: true, table_id: tableId, note: error });
    return { ok: false, error, table_id: tableId, sync: syncReplies };
  }
  const ladderReplies = await configureProfileLadders(indices, config);
  const failed = ladderReplies.filter((reply) => !reply.ok).length;
  if (failed) {
    const error = `${failed}/${indices.length} profile kh\u00f4ng nh\u1eadn \u0111\u01b0\u1ee3c c\u1ea5u h\u00ecnh d\u00e3y c\u01b0\u1ee3c; \u0111\u00e3 d\u1eebng nh\u00f3m.`;
    sendHopStatus({ active: false, error: true, table_id: tableId, note: error });
    return { ok: false, error, table_id: tableId, sync: syncReplies, replies: ladderReplies };
  }
  startSharedHop(tableId, picked.common_ids, config, indices);
  startGroupBetting(tableId, indices, config);
  const result = { ok: true, count: indices.length, table_id: tableId,
    table_name: picked.table_name, tables: picked.common_ids,
    per_profile_tables: picked.per_profile,
    sync: syncReplies, replies: ladderReplies, stake: ladderStake(config), config };
  sendHopStatus({ active: true, table_id: tableId,
    note: `C\u1ea3 ${indices.length} profile \u0111\u00e3 v\u00e0o ${result.table_name} (${tableId}); \u0111ang ch\u1edd tr\u1ea1ng th\u00e1i c\u01b0\u1ee3c \u0111\u1ed3ng b\u1ed9.` });
  return result;
}

ipcMain.handle('dg:auto-run', async (_event, { count, siteIds, indices } = {}) =>
  runDGGroup(count, siteIds, indices));
ipcMain.handle('febet:auto-run', async () => runDGGroup());

ipcMain.handle('febet:tables', async () => {
  const indices = Array.from(activeProfileIndices).sort((a, b) => a - b);
  if (!indices.length) return { ok: false, error: 'Chưa có profile nào đang mở.' };
  const leader = profileEngine(indices[0]);
  try {
    const current = await leader.call('dg.table', {}, 30000);
    if (current && current.ok && current.in_table && /^60\d{3,}$/.test(String(current.table_id || ''))) {
      return { ok: true, tables: [{ table_id: current.table_id,
        name: current.label || `Bàn ${current.table_id}`, online: 0 }], current_table: true };
    }
    const result = await leader.call('dg.tables', {}, 60000);
    if (!result || !result.ok || !(result.tables || []).length) {
      return { ok: false, error: (result && result.error) || 'Chưa đọc được bàn thật từ sảnh DG.' };
    }
    return { ok: true, tables: result.tables, current_table: false };
  } catch (error) {
    return { ok: false, error: error.message || 'Không đọc được danh sách bàn DG.' };
  }
});

// Đồng bộ bằng mã bàn thật đọc từ Laya; mỗi profile giữ URL/token phiên riêng.
ipcMain.handle('febet:sync-table', async (_event, { tableId }) => {
  const indices = Array.from(activeProfileIndices).sort((a, b) => a - b);
  if (!indices.length) return { ok: false, error: 'Chưa có profile nào đang mở.' };
  let target = String(tableId || '').trim();
  let picked = null;
  if (!target) {
    // Không có mã bàn chỉ định: vẫn phải giữ nguyên tắc "cùng một bàn cho mọi
    // profile", nên lấy bàn chung của tất cả sảnh thay vì bàn của profile dẫn đầu.
    try {
      const scans = await Promise.allSettled(indices.map((index) =>
        profileEngine(index).call('dg.tables', {}, 60000)));
      picked = pickSharedTable(scans.map((result) =>
        result.status === 'fulfilled' ? (result.value?.tables || []) : []));
    } catch (error) {
      return { ok: false, error: error.message || 'Không đọc được danh sách bàn của các sảnh DG.' };
    }
    if (!picked?.ok) {
      return { ok: false, error: picked?.error || 'Không đọc được danh sách bàn của sảnh DG.' };
    }
    target = String(picked.table_id);
  }
  if (!/^60[0-9]{3,}$/.test(target)) {
    return { ok: false, error: 'Mã bàn DG không hợp lệ; mã bàn Baccarat DG phải thuộc dải 60xxx (ví dụ 60102).' };
  }
  const results = await Promise.allSettled(indices.map((index) =>
    profileEngine(index).call('dg.syncTable', { table_id: target }, 180000)));
  const replies = results.map((result, offset) => result.status === 'fulfilled'
    ? { index: indices[offset], ...result.value }
    : { index: indices[offset], ok: false, error: result.reason.message });
  const notReady = replies.filter((reply) => !reply.ok || reply.in_table !== true
    || (reply.table_id !== undefined && String(reply.table_id) !== target));
  if (notReady.length) {
    return { ok: false, count: indices.length, table_id: target, replies,
      error: `${notReady.length}/${indices.length} profile chưa xác nhận vào bàn ${target}.` };
  }
  return { ok: true, count: indices.length, table_id: target, replies,
    tables: picked?.common_ids || [target] };
});

function ladderStake(config) {
  const first = config.stakes[0] || config.min_t;
  return Math.max(config.min_t, Math.min(config.max_t, first));
}

async function configureProfileLadders(indices, config) {
  const oddSide = config.split === 'odd-b' ? 'B' : 'P';
  const evenSide = oddSide === 'P' ? 'B' : 'P';
  const replies = await Promise.allSettled(indices.map((index) => {
    const side = index % 2 === 1 ? oddSide : evenSide;
    return profileEngine(index).call('bet.ladder.configure', {
      ...config,
      side,
    }, 30000).then((reply) => ({ index, side, ...reply }));
  }));
  return replies.map((result, offset) => result.status === 'fulfilled' ? result.value
    : { index: indices[offset], ok: false, error: result.reason.message });
}

ipcMain.handle('activity-log:get', async () => {
  await activityLogQueue;
  try {
    const rows = JSON.parse(await fs.promises.readFile(activityLogPath(), 'utf8'));
    return { ok: true, rows: Array.isArray(rows) ? rows : [] };
  } catch { return { ok: true, rows: [] }; }
});

ipcMain.handle('activity-log:clear', async () => {
  activityLogQueue = activityLogQueue.then(() => fs.promises.writeFile(activityLogPath(), '[]', 'utf8'));
  await activityLogQueue;
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('activity-log:clear');
  return { ok: true };
});

ipcMain.handle('bets:config:get', async () => ({ ok: true, config: await loadBetConfig() }));

ipcMain.handle('bets:config:save', async (_event, { config: value }) => {
  const config = await saveBetConfig(value || {});
  const indices = Array.from(activeProfileIndices).sort((a, b) => a - b);
  if (indices.length < config.min_tk) {
    return { ok: true, saved: true, applied: false, config,
      note: `Đã lưu cấu hình; cần ít nhất ${config.min_tk} profile đang mở để áp dụng dãy cược.` };
  }
  const replies = await configureProfileLadders(indices, config);
  const failed = replies.filter((reply) => !reply.ok).length;
  return { ok: failed === 0, saved: true, applied: true, config, count: indices.length,
    replies, note: failed ? `${failed} profile chưa nhận được cấu hình dãy cược.`
      : `Đã lưu và áp dụng dãy cược cho ${indices.length} profile.` };
});

// Configure opposite sides and the shared stake ladder for all open profiles.
ipcMain.handle('bets:apply', async (_event, { tableId, tableIds } = {}) => {
  const indices = Array.from(activeProfileIndices).sort((a, b) => a - b);
  if (!indices.length) return { ok: false, error: 'Chưa có profile nào đang mở.' };
  const config = await loadBetConfig();
  if (indices.length < config.min_tk) {
    return { ok: false, error: `Cấu hình yêu cầu tối thiểu ${config.min_tk} profile; hiện có ${indices.length}.` };
  }
  const replies = await configureProfileLadders(indices, config);
  const failed = replies.filter((reply) => !reply.ok).length;
  if (failed === 0 && /^60\d{3,}$/.test(String(tableId || ''))) {
    startSharedHop(tableId, tableIds, config, indices);
    startGroupBetting(tableId, indices, config);
  }
  return { ok: failed === 0, count: indices.length, stake: ladderStake(config),
    config, replies, error: failed ? `${failed} profile không nhận được cấu hình dãy cược.` : '' };
});

ipcMain.handle('bets:start-open', async (_event, { config: submittedConfig } = {}) => {
  const indices = Array.from(activeProfileIndices).sort((a, b) => a - b);
  if (!indices.length) return { ok: false, error: 'Ch\u01b0a c\u00f3 profile \u0111ang m\u1edf do \u1ee9ng d\u1ee5ng qu\u1ea3n l\u00fd.' };
  const config = submittedConfig ? await saveBetConfig(submittedConfig) : await loadBetConfig();
  if (indices.length < config.min_tk) {
    return { ok: false, error: `C\u1ea7n ${config.min_tk} profile theo c\u1ea5u h\u00ecnh, hi\u1ec7n c\u00f3 ${indices.length}.` };
  }
  const reads = await Promise.allSettled(indices.map((index) =>
    profileEngine(index).call('dg.betState', {}, 15000)));
  const states = reads.map((entry) => entry.status === 'fulfilled' ? entry.value : null);
  const notReady = states.map((state, offset) => ({ index: indices[offset], state }))
    .filter(({ state }) => !state?.ok || state.in_table !== true
      || !/^60[0-9]{3,}$/.test(String(state.table_id || '')));
  if (notReady.length) {
    const detail = notReady.map(({ index, state }) =>
      `P${index}: ${state?.error || 'ch\u01b0a \u1edf trong b\u00e0n DG'}`).join(' \u00b7 ');
    return { ok: false, error: `C\u00f3 profile ch\u01b0a \u1edf trong b\u00e0n DG: ${detail}. Kh\u00f4ng m\u1edf l\u1ea1i Chrome.` };
  }
  const tableIds = new Set(states.map((state) => String(state.table_id)));
  if (tableIds.size !== 1) {
    return { ok: false, error: `Profile \u0111ang \u1edf nhi\u1ec1u b\u00e0n DG (${[...tableIds].join('/')}); h\u00e3y \u0111\u01b0a ch\u00fang v\u1ec1 c\u00f9ng b\u00e0n tr\u01b0\u1edbc.` };
  }
  const hasExistingBet = states.some((state) => ['pending', 'confirmed'].some((kind) =>
    Object.values(state[kind] || {}).some((amount) => Number(amount) > 0)));
  if (hasExistingBet) {
    return { ok: false, error: 'Ph\u00e1t hi\u1ec7n chip \u0111\u00e3 \u0111\u1eb7t ho\u1eb7c \u0111\u00e3 x\u00e1c nh\u1eadn trong v\u00e1n hi\u1ec7n t\u1ea1i; \u0111\u00e3 kh\u00f4ng kh\u1edfi \u0111\u1ed9ng \u0111\u1ec3 tr\u00e1nh c\u01b0\u1ee3c tr\u00f9ng.' };
  }
  const tableId = String(states[0].table_id);
  if (groupBetting?.active) {
    const sameIndices = groupBetting.indices.length === indices.length
      && indices.every((index, offset) => index === groupBetting.indices[offset]);
    if (!sameIndices || groupBetting.tableId !== tableId) {
      return { ok: false, error: 'A betting session is already active for a different profile group or table.' };
    }
  }
  const ladderReplies = await configureProfileLadders(indices, config);
  const failed = ladderReplies.filter((reply) => !reply.ok);
  if (failed.length) {
    return { ok: false, error: `${failed.length} profile kh\u00f4ng nh\u1eadn \u0111\u01b0\u1ee3c c\u1ea5u h\u00ecnh d\u00e3y c\u01b0\u1ee3c.`,
      replies: ladderReplies };
  }
  if (groupBetting?.active) {
    groupBetting.config = config;
    if (sharedHop?.active) {
      sharedHop.config.total_bet = config.total_bet;
      sharedHop.schedule = configuredHopRounds(config.hop_min);
      sharedHop.maxHops = config.hop_max;
    }
    appendActivityLog({ source: 'ch\u1ea1y c\u01b0\u1ee3c', level: 'info',
      text: `\u0110\u00e3 c\u1eadp nh\u1eadt c\u1ea5u h\u00ecnh cho phi\u00ean c\u01b0\u1ee3c \u0111ang ch\u1ea1y; Chrome v\u00e0 b\u00e0n ${tableId} \u0111\u01b0\u1ee3c gi\u1eef nguy\u00ean.` });
    void groupBettingTick();
    return { ok: true, updated: true, count: indices.length, table_id: tableId,
      table_name: states[0].table_name || states[0].label || `B\u00e0n ${tableId}`,
      replies: ladderReplies, stake: ladderStake(config) };
  }
  let availableTables = [tableId];
  try {
    const result = await profileEngine(indices[0]).call('dg.tables', {}, 10000);
    const found = (result?.tables || []).map((row) => String(row.table_id || ''))
      .filter((id) => /^60[0-9]{3,}$/.test(id));
    if (found.includes(tableId)) availableTables = [...new Set(found)];
  } catch { /* current table remains a safe one-table schedule */ }
  startSharedHop(tableId, availableTables, config, indices);
  startGroupBetting(tableId, indices, config);
  appendActivityLog({ source: 'ch\u1ea1y c\u01b0\u1ee3c', level: 'info',
    text: `\u0110\u00e3 kh\u1edfi \u0111\u1ed9ng c\u01b0\u1ee3c cho ${indices.length} profile \u0111ang m\u1edf t\u1ea1i b\u00e0n ${tableId}; kh\u00f4ng m\u1edf l\u1ea1i Chrome.` });
  return { ok: true, count: indices.length, table_id: tableId,
    table_name: states[0].table_name || states[0].label || `B\u00e0n ${tableId}`,
    replies: ladderReplies, stake: ladderStake(config) };
});

ipcMain.handle('profile:fingerprint', async (_event, { index } = {}) => {
  const engine = profileEngine(Math.trunc(Number(index)));
  if (!engine) return { ok: false, error: 'Hãy mở profile trước khi xem dấu vết thiết bị.' };
  return engine.call('fingerprint.info', {}, 20000);
});

ipcMain.handle('profile:regenerateFingerprint', async (_event, { index } = {}) => {
  const engine = profileEngine(Math.trunc(Number(index)));
  if (!engine) return { ok: false, error: 'Hãy mở profile trước khi đổi dấu vết thiết bị.' };
  return engine.call('fingerprint.regenerate', {}, 30000);
});

ipcMain.handle('profile:close', async (_event, { index }) => {
  const profileIndex = Math.trunc(Number(index));
  if (!Number.isInteger(profileIndex) || profileIndex < 1 || profileIndex > 8) {
    return { ok: false, error: 'Profile không hợp lệ.' };
  }
  const engine = profileEngine(profileIndex);
  if (!engine) return { ok: true, note: 'Profile chưa được mở.' };
  try {
    const reply = await engine.call('profile.configure', { close: true });
    if (!reply || !reply.ok) return reply || { ok: false, error: 'Không đóng được profile.' };
    activeProfileIndices.delete(profileIndex);
    await closeProfileBridge(profileIndex);
    const omni = activeOmniProfiles.get(profileIndex);
    activeOmniProfiles.delete(profileIndex);
    if (omni) await stopOmniProfile(omni);
    await forgetOmniConnection(profileIndex).catch(() => {});
    return reply;
  } catch (error) {
    return { ok: false, error: error.message || 'Không đóng được profile.' };
  }
});

// Lưới an toàn cuối: Electron biến mọi exception chưa bắt ở main process thành hộp
// thoại đỏ "A JavaScript error occurred in the main process" và app đứng. Ghi log rồi
// tiếp tục để người dùng thấy nguyên nhân trong tab Nhật ký thay vì bị chặn.
function reportMainError(kind, error) {
  const text = `${kind}: ${String((error && error.stack) || (error && error.message) || error).split('\n')[0]}`;
  console.error(text);
  for (const engine of Object.values(engines)) {
    engine.emitEvent('log', { level: 'error', text });
  }
}

process.on('uncaughtException', (error) => reportMainError('lỗi main process', error));
process.on('unhandledRejection', (reason) => reportMainError('promise bị từ chối', reason));

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 980,
    minHeight: 650,
    frame: false,
    backgroundColor: '#0b1220',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => { mainWindow = null; });
}

ipcMain.handle('engine:call', async (_event, { game, method, params }) => {
  const engine = engines[game];
  if (!engine) throw new Error(`trò không hỗ trợ: ${game}`);
  const started = Date.now();
  try {
    const result = await engine.call(method, params || {});
    return { ok: true, result, ms: Date.now() - started };
  } catch (error) {
    return { ok: false, error: String(error.message || error), ms: Date.now() - started };
  }
});

ipcMain.handle('profiles:connections', async () => loadOmniConnections());

ipcMain.handle('profiles:forgetConnection', async (_event, { index } = {}) => {
  const profileIndex = Math.trunc(Number(index));
  if (!Number.isInteger(profileIndex) || profileIndex < 1 || profileIndex > 8) {
    return { ok: false, error: 'Profile không hợp lệ.' };
  }
  await forgetOmniConnection(profileIndex);
  return { ok: true };
});

ipcMain.handle('profiles:open', async (_event, { count, siteId, siteIds, indices, profiles, source = 'local', omniApiUrl, hidemiumApiUrl }) => {
  const requestedIndices = Array.isArray(indices)
    ? [...new Set(indices.map((value) => Math.trunc(Number(value)))
      .filter((value) => Number.isInteger(value) && value >= 1 && value <= 8))].sort((a, b) => a - b)
    : Array.from({ length: Math.max(1, Math.min(8, Math.trunc(Number(count) || 1))) }, (_, i) => i + 1);
  const total = requestedIndices.length;
  if (!total) return { ok: false, error: 'Hãy chọn ít nhất một profile để mở.' };
  const selectedSiteIds = Array.isArray(siteIds) ? siteIds : Array(total).fill(siteId);
  const sites = Array.from({ length: total }, (_, offset) =>
    sitesConfig().find((item) => item.id === selectedSiteIds[offset]));
  if (sites.some((item) => !item)) {
    return { ok: false, error: 'Hãy chọn một site hợp lệ riêng cho từng profile.' };
  }
  if (!['local', 'omni', 'hidemium'].includes(source)) return { ok: false, error: 'Nguồn profile không hợp lệ.' };
  const requested = Array.isArray(profiles) ? profiles : [];
  const proxyStore = await loadProxyStore();
  let apiUrl = '';
  let omniRows = [];
  if (source === 'omni') {
    try {
      apiUrl = normalizeOmniApiUrl(omniApiUrl);
      omniRows = Array.from({ length: total }, (_, i) => String(requested[i]?.omniProfileId || '').trim());
      if (omniRows.some((id) => !id)) {
        return { ok: false, error: 'Hãy gán một profile OmniLogin riêng cho từng profile trước khi chạy.' };
      }
      if (new Set(omniRows).size !== omniRows.length) {
        return { ok: false, error: 'Không thể gán trùng một profile OmniLogin cho nhiều cửa sổ.' };
      }
      const ports = omniRows.map(omniDebugPort);
      if (new Set(ports).size !== ports.length) {
        return { ok: false, error: 'Hai profile OmniLogin nhận cùng cổng CDP dự phòng; chọn profile khác để tránh gắn nhầm Chrome.' };
      }
      if (requested.slice(0, total).some((row, index) => row?.proxyId || row?.proxy
          || proxyStore.assignments[String(requestedIndices[index])])) {
        return { ok: false, error: 'Proxy của profile OmniLogin cần được cấu hình trong OmniLogin; bỏ proxy gán từ tab Proxy của ứng dụng trước khi chạy.' };
      }
      const available = await listOmniProfiles(apiUrl);
      if (omniRows.some((id) => !available.some((item) => item.id === id))) {
        return { ok: false, error: 'Có profile OmniLogin được gán nhưng không còn trong danh sách API.' };
      }
    } catch (error) {
      return { ok: false, error: error.message || 'Không kết nối được OmniLogin.' };
    }
  }
  let hidemiumRows = [];
  if (source === 'hidemium') {
    try {
      apiUrl = normalizeHidemiumApiUrl(hidemiumApiUrl);
      hidemiumRows = Array.from({ length: total }, (_, i) => String(requested[i]?.hidemiumProfileId || '').trim());
      if (hidemiumRows.some((id) => !id)) return { ok: false, error: 'Hãy gán một profile Hidemium riêng cho từng profile trước khi chạy.' };
      if (new Set(hidemiumRows).size !== hidemiumRows.length) return { ok: false, error: 'Không thể gán trùng một profile Hidemium cho nhiều cửa sổ.' };
      if (requested.slice(0, total).some((row, index) => row?.proxyId || row?.proxy
          || proxyStore.assignments[String(requestedIndices[index])])) {
        return { ok: false, error: 'Proxy của profile Hidemium cần được cấu hình trong Hidemium; bỏ proxy gán từ tab Proxy trước khi chạy.' };
      }
      const available = await listHidemiumProfiles(apiUrl);
      if (hidemiumRows.some((id) => !available.some((item) => item.id === id))) {
        return { ok: false, error: 'Có profile Hidemium được gán nhưng không còn trong danh sách API.' };
      }
    } catch (error) {
      return { ok: false, error: error.message || 'Không kết nối được Hidemium.' };
    }
  }
  const settings = [];
  const newBridges = [];
  try {
    for (let index = 0; index < total; index += 1) {
      const row = requested[index] || {};
      const width = Math.max(520, Math.min(3840, Math.round(Number(row.width) || 900)));
      const height = Math.max(200, Math.min(2160, Math.round(Number(row.height) || 1200)));
      const scale = Math.max(50, Math.min(200, Math.round(Number(row.scale) || 60)));
      const proxy = source === 'omni' || source === 'hidemium' ? null
        : proxyForProfile({ ...row, proxyId: row.proxyId || proxyStore.assignments[String(requestedIndices[index])] }, proxyStore);
      let proxyServer = proxyServerUrl(proxy);
      if (proxy && proxy.username) {
        const bridge = await startProxyBridge(proxy);
        newBridges.push({ index: requestedIndices[index], bridge });
        proxyServer = bridge.url;
      }
      settings.push({ index: requestedIndices[index], width, height, scale, proxyServer,
        proxyLabel: proxyLabel(proxy), bridge:
        newBridges.length && newBridges[newBridges.length - 1].index === requestedIndices[index]
          ? newBridges[newBridges.length - 1].bridge : null });
    }
  } catch (error) {
    await Promise.all(newBridges.map(({ bridge }) => bridge.close().catch(() => {})));
    return { ok: false, error: error.message || 'Cấu hình proxy không hợp lệ.' };
  }

  const { screen } = require('electron');
  const area = screen.getPrimaryDisplay().workAreaSize;
  const layouts = tileProfileLayouts(settings, area);

  const extras = Array.from(activeProfileIndices).filter((index) => !requestedIndices.includes(index));
  if (extras.length) {
    const closeResults = await Promise.allSettled(extras.map(async (index) => {
      const engine = profileEngine(index);
      if (engine) await engine.call('profile.configure', { close: true });
      await closeProfileBridge(index);
      const omni = activeOmniProfiles.get(index);
      activeOmniProfiles.delete(index);
      if (omni) await stopOmniProfile(omni);
      activeProfileIndices.delete(index);
    }));
    if (closeResults.some((item) => item.status === 'rejected')) {
      await Promise.all(newBridges.map(({ bridge }) => bridge.close().catch(() => {})));
      return { ok: false, error: 'Không đóng được các profile dư.' };
    }
  }

  const started = Array.from({ length: total }, (_, offset) => ensureProfileEngine(
    requestedIndices[offset], layouts[offset],
    source === 'omni' ? omniDebugPort(omniRows[offset]) : null));

  for (let offset = 0; offset < total; offset += 1) {
    const index = requestedIndices[offset];
    const previousOmni = activeOmniProfiles.get(index);
    const providerRows = source === 'omni' ? omniRows : hidemiumRows;
    const keep = (source === 'omni' || source === 'hidemium') && previousOmni
      && previousOmni.provider === source && previousOmni.profileId === providerRows[offset]
      && previousOmni.apiUrl === apiUrl;
    if (previousOmni && !keep) {
      await profileEngine(index).call('profile.configure', { close: true }).catch(() => {});
      await stopOmniProfile(previousOmni);
      activeOmniProfiles.delete(index);
      activeProfileIndices.delete(index);
    }
  }

  const configured = await Promise.allSettled(started.map((engine, index) => engine.call('profile.configure', {
    url: sites[index].url,
    proxy_server: layouts[index].proxyServer,
    width: layouts[index].width,
    height: layouts[index].height,
    scale: layouts[index].scale,
    left: layouts[index].left,
    top: layouts[index].top,
    cdp_port: engine.cdpPort,
  })));
  const openResults = await Promise.allSettled(started.map(async (engine, index) => {
    const profileIndex = requestedIndices[index];
    const result = configured[index];
    if (result.status !== 'fulfilled' || !result.value.ok) return { ok: false,
      error: result.status === 'rejected' ? result.reason.message : result.value.error,
      proxy: settings[index].proxyLabel };
    if (source === 'omni' || source === 'hidemium') {
      const providerRows = source === 'omni' ? omniRows : hidemiumRows;
      const previousOmni = activeOmniProfiles.get(profileIndex);
      if (previousOmni && (previousOmni.profileId !== providerRows[index] || previousOmni.provider !== source)) {
        await stopOmniProfile(previousOmni);
        activeOmniProfiles.delete(profileIndex);
      }
      const omni = source === 'omni' ? await openOmniProfile(apiUrl, providerRows[index])
        : await openHidemiumProfile(apiUrl, providerRows[index]);
      activeOmniProfiles.set(profileIndex, omni);
      await rememberOmniConnection(profileIndex, omni, source, apiUrl).catch(() => {});
      const attached = await engine.call('chrome.attachExternal', {
        port: omni.port, width: settings[index].width, height: settings[index].height, provider: source,
      }, 45000);
      if (!attached?.ok) {
        await stopOmniProfile(omni);
        activeOmniProfiles.delete(profileIndex);
        return { ok: false, error: attached?.error || `Không gắn được Chrome profile ${source === 'omni' ? 'OmniLogin' : 'Hidemium'}.` };
      }
    } else {
      const previousOmni = activeOmniProfiles.get(profileIndex);
      if (previousOmni) {
        await stopOmniProfile(previousOmni);
        activeOmniProfiles.delete(profileIndex);
      }
    }
    const reply = await engine.call('site.open', { url: sites[index].url }, 45000);
    if ((!reply || !reply.ok) && (source === 'omni' || source === 'hidemium')) {
      // Keep the managed profile registered: OmniLogin/Hidemium own the browser,
      // and asking them to stop would close the window the user is watching.
      activeProfileIndices.add(profileIndex);
    }
    return { ...reply, index: profileIndex, site: sites[index].label,
      device: configured[index]?.value?.device || '',
      proxy: source === 'omni' || source === 'hidemium' ? `Proxy theo cấu hình ${source === 'omni' ? 'OmniLogin' : 'Hidemium'}` : settings[index].proxyLabel,
      width: settings[index].width, height: settings[index].height, scale: settings[index].scale,
      ...(source === 'omni' ? { omni_profile_id: omniRows[index] } : {}),
      ...(source === 'hidemium' ? { hidemium_profile_id: hidemiumRows[index] } : {}) };
  }));

  for (let offset = 0; offset < total; offset += 1) {
    const index = requestedIndices[offset];
    const result = configured[offset];
    const setting = settings[offset];
    const openResult = openResults[offset];
    if (result.status === 'fulfilled' && result.value.ok
        && openResult.status === 'fulfilled' && openResult.value?.ok) {
      await closeProfileBridge(index);
      if (setting.bridge) activeProxyBridges.set(index, setting.bridge);
      activeProfileIndices.add(index);
    } else if (setting.bridge) {
      await setting.bridge.close().catch(() => {});
      activeProfileIndices.delete(index);
    } else {
      activeProfileIndices.delete(index);
    }
  }
  const replies = openResults.map((result, index) => result.status === 'fulfilled'
    ? result.value : { ok: false, error: result.reason.message, proxy: settings[index].proxyLabel });
  return { ok: true, count: total, indices: requestedIndices,
    site: sites.map((item) => item.label).join(' / '),
    sites: sites.map((item) => item.label), source, replies };
});

ipcMain.handle('profiles:close', async () => {
  const indices = Array.from(activeProfileIndices);
  const targets = indices.map((index) => ({ index, engine: profileEngine(index) })).filter((item) => item.engine);
  const replies = await Promise.allSettled(targets.map(({ engine }) => engine.call('profile.configure', { close: true })));
  await Promise.all(indices.map(async (index) => {
    const omni = activeOmniProfiles.get(index);
    activeOmniProfiles.delete(index);
    if (omni) await stopOmniProfile(omni);
  }));
  await Promise.all(Array.from(activeProxyBridges.keys(), (index) => closeProfileBridge(index)));
  activeProfileIndices.clear();
  return { ok: true, count: targets.length, replies: replies.map((result) => result.status === 'fulfilled'
    ? result.value : { ok: false, error: result.reason.message }) };
});

ipcMain.handle('proxy:list', async () => {
  const store = await loadProxyStore();
  return { items: store.items.map(publicProxyItem).filter(Boolean), assignments: store.assignments };
});

ipcMain.handle('proxy:import', async (_event, { text }) => {
  const store = await loadProxyStore();
  const known = new Set(store.items.map((item) => {
    try {
      const proxy = parseProxy(item.value);
      return `${proxy.protocol}|${proxy.host}|${proxy.port}|${proxy.username}`;
    } catch { return ''; }
  }));
  const invalid = [];
  let added = 0;
  let duplicate = 0;
  for (const [index, rawLine] of String(text || '').split(/\r?\n/).entries()) {
    const value = rawLine.trim();
    if (!value || value.startsWith('#') || value.startsWith('//')) continue;
    let proxy;
    try { proxy = parseProxy(value); }
    catch (error) { invalid.push({ line: index + 1, message: error.message }); continue; }
    const key = `${proxy.protocol}|${proxy.host}|${proxy.port}|${proxy.username}`;
    if (known.has(key)) { duplicate += 1; continue; }
    known.add(key);
    store.items.push({ id: randomUUID(), value, status: 'unchecked', message: '', checkedAt: null });
    added += 1;
  }
  if (added) await saveProxyStore(store);
  return { ok: true, added, duplicate, invalid, items: store.items.map(publicProxyItem).filter(Boolean),
    assignments: store.assignments };
});

ipcMain.handle('proxy:remove', async (_event, { id }) => {
  const store = await loadProxyStore();
  const before = store.items.length;
  store.items = store.items.filter((item) => item.id !== id);
  for (const [profile, assigned] of Object.entries(store.assignments)) {
    if (assigned === id) delete store.assignments[profile];
  }
  if (store.items.length !== before) await saveProxyStore(store);
  return { ok: true, items: store.items.map(publicProxyItem).filter(Boolean), assignments: store.assignments };
});

ipcMain.handle('proxy:assign', async (_event, { profile, proxyId }) => {
  const index = Math.trunc(Number(profile));
  if (!Number.isInteger(index) || index < 1 || index > 8) return { ok: false, error: 'Profile không hợp lệ.' };
  const store = await loadProxyStore();
  if (proxyId && !store.items.some((item) => item.id === proxyId)) {
    return { ok: false, error: 'Không tìm thấy proxy cần gán.' };
  }
  if (proxyId) store.assignments[String(index)] = proxyId;
  else delete store.assignments[String(index)];
  await saveProxyStore(store);
  return { ok: true, assignments: store.assignments };
});

ipcMain.handle('proxy:check', async () => {
  const store = await loadProxyStore();
  const queue = store.items.map((item, index) => ({ item, index }));
  const workers = Array.from({ length: Math.min(8, queue.length) }, async () => {
    while (queue.length) {
      const next = queue.shift();
      let result;
      try { result = await checkProxy(parseProxy(next.item.value)); }
      catch { result = { ok: false, message: 'Proxy không hợp lệ.' }; }
      next.item.status = result.ok ? 'live' : 'dead';
      next.item.message = result.message;
      next.item.checkedAt = new Date().toISOString();
    }
  });
  await Promise.all(workers);
  await saveProxyStore(store);
  const items = store.items.map(publicProxyItem).filter(Boolean);
  return { ok: true, items, assignments: store.assignments,
    live: items.filter((item) => item.status === 'live').length,
    dead: items.filter((item) => item.status === 'dead').length };
});

ipcMain.handle('omni:profiles', async (_event, { apiUrl }) => {
  try {
    const normalized = normalizeOmniApiUrl(apiUrl);
    const profiles = await listOmniProfiles(normalized);
    return { ok: true, apiUrl: normalized, profiles };
  } catch (error) {
    return { ok: false, error: error.message || 'Không kết nối được OmniLogin API.' };
  }
});

ipcMain.handle('hidemium:profiles', async (_event, { apiUrl }) => {
  try {
    const normalized = normalizeHidemiumApiUrl(apiUrl);
    const profiles = await listHidemiumProfiles(normalized);
    return { ok: true, apiUrl: normalized, profiles };
  } catch (error) {
    return { ok: false, error: error.message || 'Không kết nối được Hidemium API.' };
  }
});

function publicSites() {
  return sitesConfig().map(({ id, label, url, chips, auto }) => ({
    id, label, url, chips, auto,
    display: siteOptionLabel({ label, chips }),
    // True only when the backend actually has an entry adapter for this id.
    automation: ['febet', 'gk881', 'e3951', 'vnwtop'].includes(id),
  }));
}

ipcMain.handle('app:info', () => ({
  version: app.getVersion(),
  root: PROJECT_ROOT,
  engines: Object.keys(engines),
  profileSites: publicSites(),
}));

ipcMain.handle('sites:list', () => ({ ok: true, sites: publicSites() }));

ipcMain.handle('sites:create', async (_event, { site } = {}) => {
  const sites = sitesConfig();
  const next = normalizeSite(site);
  const error = validateSite(next, sites);
  if (error) return { ok: false, error };
  if (!sites.some((item) => item.id === next.id)) {
    await saveSitesConfig([...sites, next]);
  }
  return { ok: true, sites: publicSites() };
});

ipcMain.handle('sites:update', async (_event, { site } = {}) => {
  const sites = sitesConfig();
  const originalId = String(site?.originalId || site?.id || '').trim().toLowerCase();
  const index = sites.findIndex((item) => item.id === originalId);
  if (index < 0) return { ok: false, error: 'Không tìm thấy site cần sửa.' };
  const next = normalizeSite(site);
  // Allow keeping the same id, or renaming to a free one.
  const error = validateSite(next, sites, { allowSameId: originalId });
  if (error) return { ok: false, error };
  const updated = sites.slice();
  updated[index] = next;
  await saveSitesConfig(updated);
  return { ok: true, sites: publicSites() };
});

// Thứ tự site trong store chính là thứ tự option ở dropdown của từng profile.
// "top" đưa lên vị trí 1, "up"/"down" dịch một bậc; đã ở biên thì báo chứ không lỗi.
ipcMain.handle('sites:reorder', async (_event, { id, action } = {}) => {
  const result = reorderSites(sitesConfig(), id, action);
  if (!result.ok) return result;
  if (result.moved) await saveSitesConfig(result.sites);
  return { ok: true, sites: publicSites(), moved: result.moved, note: result.note };
});

ipcMain.handle('sites:delete', async (_event, { id } = {}) => {
  const sites = sitesConfig();
  const target = String(id || '').trim().toLowerCase();
  const remaining = sites.filter((item) => item.id !== target);
  if (remaining.length === sites.length) return { ok: false, error: 'Không tìm thấy site cần xoá.' };
  if (!remaining.length) return { ok: false, error: 'Phải giữ lại ít nhất một site.' };
  await saveSitesConfig(remaining);
  return { ok: true, sites: publicSites() };
});

ipcMain.handle('sites:reset', async () => {
  const sites = await saveSitesConfig(DEFAULT_SITES.map((item) => ({ ...item })));
  return { ok: true, sites: publicSites(), note: `Đã khôi phục ${sites.length} site mặc định.` };
});

ipcMain.handle('app:openExternal', (_event, url) => shell.openExternal(url));

// Lưu file text (CSV lịch sử bàn) qua hộp thoại của Windows.
ipcMain.handle('app:saveText', async (_event, { name, text }) => {
  try {
    const result = await dialog.showSaveDialog(mainWindow, {
      title: 'Lưu file',
      defaultPath: path.join(PROJECT_ROOT, name || 'aibcr-export.csv'),
      filters: [{ name: 'CSV', extensions: ['csv'] }, { name: 'Tất cả', extensions: ['*'] }],
    });
    if (result.canceled || !result.filePath) return { ok: false, error: 'Đã huỷ lưu file.' };
    await fs.promises.writeFile(result.filePath, String(text ?? ''), 'utf8');
    return { ok: true, path: result.filePath };
  } catch (error) {
    return { ok: false, error: `Không lưu được file: ${error.message || error}` };
  }
});

ipcMain.on('window:control', (_event, action) => {
  if (!mainWindow) return;
  if (action === 'minimize') mainWindow.minimize();
  else if (action === 'maximize') {
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
  } else if (action === 'close') mainWindow.close();
});

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('before-quit', () => {
  Object.values(engines).forEach((engine) => engine.stop());
  for (const bridge of activeProxyBridges.values()) bridge.close().catch(() => {});
  activeProxyBridges.clear();
});

app.on('window-all-closed', () => {
  Object.values(engines).forEach((engine) => engine.stop());
  if (process.platform !== 'darwin') app.quit();
});
