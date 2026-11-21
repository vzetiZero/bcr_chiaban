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

const PROFILE_SITES = [
  { id: 'febet', label: 'FEBET Baccarat', url: 'https://febet.kiwi/live-casino/baccarat?a=c76811abcadb64fed7d82b32d7e79f3c&utm_campaign=social&utm_source=aphonso&utm_medium=sale&utm_term=bee&utm_content=KANGIN&event=' },
  { id: 'e3951', label: 'E3951', url: 'https://e39d5d05qc.e3951.com/m/gameRecord' },
  { id: 'gk881', label: 'GK881', url: 'https://m.gk881.vip/' },
  { id: 'vnwtop', label: 'VNWTop', url: 'https://vnwtop.com/' },
  { id: '888ae66', label: '888AE66', url: 'https://www.888ae66.com/' },
  { id: 'bum123', label: 'BUM123', url: 'https://www.bum123.com/aff/10459' },
];

const DEFAULT_BET_CONFIG = Object.freeze({
  stakes: [260, 280, 300, 240, 220, 280, 320, 340, 380, 400, 360, 420,
    440, 480, 500, 420, 340, 380, 440, 280, 400, 360, 300, 340, 280,
    400, 360, 300, 280],
  min_t: 20,
  max_t: 10000,
  min_tk: 3,
  total_bet: 5000,
  hop_min: '2',
  hop_max: 5,
  split: 'odd-p',
  auto_confirm: false,
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
  const min_tk = Math.max(2, Math.min(15, Math.trunc(Number(value.min_tk) || 3)));
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
    auto_confirm: value.auto_confirm === true,
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

function stopGroupBetting(note, error = true) {
  if (groupBetTimer) clearInterval(groupBetTimer);
  groupBetTimer = null;
  if (groupBetting) groupBetting.active = false;
  if (sharedHop) sharedHop.active = false;
  groupStatus(note, error);
}

function normalizedWinner(states) {
  const winners = states.map((state) => state.winner);
  return winners.length && winners[0] && winners.every((winner) => winner === winners[0])
    ? winners[0] : '';
}

async function settleGroupRound(states, placed) {
  if (!placed || placed.settled) return false;
  const winner = normalizedWinner(states);
  if (!winner) return false;
  const updates = await Promise.allSettled(placed.indices.map((index, offset) => {
    const outcome = winner === 'T' ? 'PUSH' : winner === placed.sides[offset] ? 'WIN' : 'LOSS';
    return profileEngine(index).call('bet.ladder.result', { outcome }, 30000);
  }));
  if (updates.some((entry) => entry.status !== 'fulfilled' || !entry.value?.ok)) {
    stopGroupBetting('Kết quả ván đã đọc được nhưng chưa cập nhật được mọi dãy cược; đã dừng nhóm.', true);
    return false;
  }
  placed.settled = true;
  groupBetting.totalWagered += placed.stakes.reduce((sum, stake) => sum + stake, 0);
  if (sharedHop?.active) {
    sharedHop.rounds += 1;
    const threshold = sharedHop.schedule[sharedHop.hops % sharedHop.schedule.length];
    groupStatus(`Đã xác nhận kết quả ván ${sharedHop.rounds}/${threshold}; tổng cược ${groupBetting.totalWagered}k.`);
    if (sharedHop.config.total_bet > 0 && !sharedHop.targetNotified
        && groupBetting.totalWagered >= sharedHop.config.total_bet) {
      sharedHop.targetNotified = true;
      groupStatus(`Đã đạt mục tiêu tổng cược ${groupBetting.totalWagered}/${sharedHop.config.total_bet}k.`);
    }
    if (sharedHop.rounds >= threshold) await rotateSharedProfiles();
  } else {
    groupStatus(`Đã quyết toán ván ${placed.roundId}; kết quả ${winner}.`);
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
      groupStatus('Chờ tất cả profile tải xong trạng thái bàn DG.');
      return;
    }
    const roundIds = new Set(states.map((state) => String(state.round_id)));
    if (roundIds.size !== 1) {
      groupStatus('Các profile chưa đồng bộ cùng mã ván; chưa đặt chip.');
      return;
    }
    const roundId = String(states[0].round_id);
    if (groupBetting.lastPlaced && groupBetting.lastPlaced.roundId !== roundId
        && !groupBetting.lastPlaced.settled) {
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
      const settled = await settleGroupRound(states, prior);
      if (!settled) {
        stopGroupBetting('Không xác nhận được kết quả ván trước từ Laya; đã dừng để không đoán bước dãy cược.', true);
        return;
      }
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
      if (!states.some((state) => state.bet_open) && !placed.settled) {
        await settleGroupRound(states, placed);
      }
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
        return `P${index}: scale=${state.scale ?? '?'}, floor_src=${state.floor_source || '?'}, raw_min=${state.raw_min ?? '?'}, screen_min=${state.screen_floor ?? '?'}, table_min=${state.min_k ?? '?'}k, table_max=${state.max_k || '?'}k, balance=${state.balance_k ?? '?'}k, chips=[${(state.denominations_k || []).join(',')}]`;
      }).join(' · ');
      appendActivityLog({ source: 'kiểm tra chip', level: 'error',
        text: `Không tìm thấy mức chung không vượt ${targetStake}k. ${diagnostics}` });
      stopGroupBetting(`Kh\u00f4ng c\u00f3 m\u1ee9c chip chung h\u1ee3p l\u1ec7 kh\u00f4ng v\u01b0\u1ee3t ${targetStake}k; \u0111\u00e3 d\u1eebng tr\u01b0\u1edbc khi x\u1ebfp chip.`, true);
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
      stopGroupBetting(`Không xếp đủ chip cho cả nhóm; dừng và không tự thử lại. ${details}`, true);
      return;
    }
    groupBetting.lastPlaced = { roundId, indices: [...groupBetting.indices], sides, stakes,
      confirmed: replies.every((reply) => reply.confirmed === true), settled: false };
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
  if (!PROFILE_SITES.some((site) => site.url === url)) {
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
        await stopOmniProfile(omni);
        return { ok: false, error: navigated?.error || 'Không mở được website trong profile.' };
      }
    }
    if (omni) activeOmniProfiles.set(profileIndex, omni);
    else activeOmniProfiles.delete(profileIndex);
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

async function runDGGroup(count, siteIds) {
  const indices = Array.from(activeProfileIndices).sort((a, b) => a - b);
  if (!indices.length) return { ok: false, error: 'Hãy mở profile trước, tự vào site và mở sảnh DG rồi mới chạy đồng bộ nhóm.' };
  const requested = Math.max(1, Math.min(8, Math.trunc(Number(count) || indices.length)));
  if (indices.length !== requested || indices.some((index, offset) => index !== offset + 1)) {
    return { ok: false, error: `Đã chọn ${requested} profile nhưng đang mở ${indices.length}. Hãy mở đúng các Profile 1–${requested} trước khi chạy.` };
  }
  const config = await loadBetConfig();
  if (indices.length < config.min_tk) {
    return { ok: false, error: `C\u1ea5u h\u00ecnh y\u00eau c\u1ea7u t\u1ed1i thi\u1ec3u ${config.min_tk} profile; hi\u1ec7n c\u00f3 ${indices.length}.` };
  }
  const selectedSites = Array.isArray(siteIds) ? siteIds.map((id) => String(id || ''))
    : indices.map(() => 'febet');
  if (selectedSites.length !== indices.length
      || selectedSites.some((id) => !PROFILE_SITES.some((site) => site.id === id))) {
    return { ok: false, error: 'Mỗi profile cần có một site hợp lệ trước khi vào sảnh DG.' };
  }
  const febetIndices = indices.filter((_, offset) => selectedSites[offset] === 'febet');
  const febetAutoStates = new Map();
  if (febetIndices.length) {
    const labels = febetIndices.map((index) => `Profile ${index}`).join(', ');
    sendHopStatus({ active: true, waiting_indices: [...indices],
      note: `Đang tự vào sảnh DG cho ${labels} qua FEBET; các profile site khác vào sảnh thủ công.` });
    const autoResults = await Promise.allSettled(febetIndices.map((index) =>
      profileEngine(index).call('febet.openDG', {}, 360000)));
    autoResults.forEach((result, offset) => {
      const index = febetIndices[offset];
      const reply = result.status === 'fulfilled' ? result.value : { ok: false, error: result.reason.message };
      febetAutoStates.set(index, reply?.ok
        ? { ready: true, note: reply.clicked_image
          ? `Đã bấm thẻ Dream Gaming${reply.clicked_xem_game ? ' và XEM GAME' : '; đang chờ nút XEM GAME/game tải'}.`
          : 'Game DG đã mở sẵn trên FEBET; đang xác nhận trạng thái.' }
        : { ready: false, note: `FEBET chưa tự mở được DG (${reply?.error || 'chưa xác nhận'}); có thể vào sảnh thủ công.` });
    });
    sendHopStatus({ active: true, waiting_indices: [...indices],
      profile_states: indices.map((index) => ({ index, ready: febetAutoStates.get(index)?.ready || false,
        note: febetAutoStates.get(index)?.note || 'Profile site này cần vào sảnh DG thủ công.' })),
      note: 'Đã chạy thao tác vào DG cho profile FEBET. Đang quét các profile mỗi 5 giây để xác nhận và đồng bộ nhóm.' });
  }
  sendHopStatus({ active: true,
    note: febetIndices.length
      ? 'FEBET đang/đã tự vào DG; hãy tự vào sảnh trên các profile site khác. Ứng dụng quét mỗi 5 giây.'
      : 'Các site đã mở. Hãy tự vào sảnh DG trên từng profile; ứng dụng sẽ quét trạng thái mỗi 5 giây.',
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
      return { index, ready, in_table: result?.in_table === true,
        note: ready ? (result.in_table ? `Đã thấy đang ở bàn ${result.table_id || ''}.` : 'Đã nhận diện sảnh DG.')
          : (febetAutoStates.get(index)?.note || `Đang chờ sảnh DG${result?.error ? ` · ${result.error}` : ''}.`) };
    });
    const waiting = profileStates.filter((item) => !item.ready).map((item) => item.index);
    if (!waiting.length) break;
    for (let countdown = 5; countdown >= 0; countdown -= 1) {
      sendHopStatus({ active: true, countdown, waiting_indices: waiting, profile_states: profileStates,
        note: countdown === 0 ? `Đang quét lại sảnh DG cho profile ${waiting.join(', ')}...`
          : `Đang chờ profile ${waiting.join(', ')} vào sảnh DG · quét lại sau ${countdown} giây.` });
      if (countdown > 0) await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
  if (!indices.every((index) => activeProfileIndices.has(index))) {
    const error = 'Đã dừng chờ sảnh vì một hoặc nhiều profile đã được đóng.';
    sendHopStatus({ active: false, error: true, note: error });
    return { ok: false, cancelled: true, error, profile_states: profileStates };
  }
  sendHopStatus({ active: true, profile_states: profileStates,
    note: 'Đã thấy sảnh DG trên tất cả profile; đang đọc danh sách bàn để đồng bộ nhóm...' });
  const leader = profileEngine(indices[0]);
  let scan = null;
  let tables = [];
  while (indices.every((index) => activeProfileIndices.has(index))) {
    try {
      scan = await leader.call('dg.tables', { wait: 0 }, 10000);
      tables = (scan?.tables || []).filter((row) => /^60[0-9]{3,}$/.test(String(row.table_id || '')));
      if (scan?.ok && tables.length) break;
    } catch (error) {
      scan = { ok: false, error: error.message };
    }
    for (let countdown = 5; countdown >= 0; countdown -= 1) {
      sendHopStatus({ active: true, countdown, profile_states: profileStates,
        note: countdown === 0 ? 'Đang quét danh sách bàn DG...'
          : `Đã nhận diện DG; chờ danh sách bàn · quét lại sau ${countdown} giây.` });
      if (countdown > 0) await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
  if (!indices.every((index) => activeProfileIndices.has(index))) {
    const error = 'Đã dừng quét bàn vì một hoặc nhiều profile đã được đóng.';
    sendHopStatus({ active: false, error: true, note: error });
    return { ok: false, cancelled: true, error, profile_states: profileStates };
  }
  if (!tables.length) {
    const reason = scan?.error || 'H\u1ebft th\u1eddi gian ch\u1edd, ch\u01b0a \u0111\u1ecdc \u0111\u01b0\u1ee3c danh s\u00e1ch b\u00e0n th\u1eadt t\u1eeb s\u1ea3nh DG.';
    sendHopStatus({ active: false, error: true, note: reason });
    return { ok: false, error: reason };
  }
  // Prefer the busiest table; use the real DG id as a stable tie-breaker.
  tables.sort((a, b) => (Number(b.online) || 0) - (Number(a.online) || 0)
    || String(a.table_id).localeCompare(String(b.table_id), undefined, { numeric: true }));
  const tableId = String(tables[0].table_id);
  sendHopStatus({ active: true, table_id: tableId,
    note: `\u0110\u00e3 t\u1ef1 ch\u1ecdn ${tables[0].name || `b\u00e0n ${tableId}`} (${tableId}); \u0111ang \u0111\u1ed3ng b\u1ed9 ${indices.length} profile...` });
  const syncResults = await Promise.allSettled(indices.map((index) =>
    profileEngine(index).call('dg.syncTable', { table_id: tableId }, 180000)));
  const syncReplies = syncResults.map((result, offset) => result.status === 'fulfilled'
    ? { index: indices[offset], ...result.value }
    : { index: indices[offset], ok: false, error: result.reason.message });
  const notReady = syncReplies.filter((reply) => !reply.ok || reply.in_table !== true);
  if (notReady.length) {
    const error = `${notReady.length}/${indices.length} profile ch\u01b0a x\u00e1c nh\u1eadn v\u00e0o b\u00e0n ${tableId}; \u0111\u00e3 d\u1eebng tr\u01b0\u1edbc khi x\u1ebfp chip.`;
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
  const tableIds = [...new Set(tables.map((row) => String(row.table_id)))];
  startSharedHop(tableId, tableIds, config, indices);
  startGroupBetting(tableId, indices, config);
  const result = { ok: true, count: indices.length, table_id: tableId,
    table_name: tables[0].name || `B\u00e0n ${tableId}`, tables: tableIds,
    sync: syncReplies, replies: ladderReplies, stake: ladderStake(config), config };
  sendHopStatus({ active: true, table_id: tableId,
    note: `C\u1ea3 ${indices.length} profile \u0111\u00e3 v\u00e0o ${result.table_name} (${tableId}); \u0111ang ch\u1edd tr\u1ea1ng th\u00e1i c\u01b0\u1ee3c \u0111\u1ed3ng b\u1ed9.` });
  return result;
}

ipcMain.handle('dg:auto-run', async (_event, { count, siteIds } = {}) => runDGGroup(count, siteIds));
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
  if (!target) {
    try {
      const leader = profileEngine(indices[0]);
      const read = await leader.call('dg.table', {}, 30000);
      if (read && read.ok && read.in_table && /^60\d{3,}$/.test(String(read.table_id || ''))) {
        target = String(read.table_id);
      } else {
        const scan = await leader.call('dg.tables', {}, 60000);
        if (!scan || !scan.ok || !(scan.tables || []).length) {
          return { ok: false, error: (scan && scan.error) || 'Không đọc được danh sách bàn của sảnh DG.' };
        }
        target = String(scan.tables[0].table_id || '');
      }
    } catch (error) {
      return { ok: false, error: error.message || 'Không đọc được bàn của profile dẫn đầu.' };
    }
  }
  if (!/^60[0-9]{3,}$/.test(target)) {
    return { ok: false, error: 'Mã bàn DG không hợp lệ; mã bàn Baccarat DG phải thuộc dải 60xxx (ví dụ 60102).' };
  }
  const results = await Promise.allSettled(indices.map((index) =>
    profileEngine(index).call('dg.syncTable', { table_id: target }, 180000)));
  return { ok: true, count: indices.length, table_id: target, replies: results.map((result, offset) =>
    result.status === 'fulfilled' ? { index: indices[offset], ...result.value }
      : { index: indices[offset], ok: false, error: result.reason.message }) };
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

ipcMain.handle('profiles:open', async (_event, { count, siteId, siteIds, profiles, source = 'local', omniApiUrl, hidemiumApiUrl }) => {
  const total = Math.max(1, Math.min(8, Math.trunc(Number(count) || 1)));
  const selectedSiteIds = Array.isArray(siteIds) ? siteIds : Array(total).fill(siteId);
  const sites = selectedSiteIds.slice(0, total).map((id) => PROFILE_SITES.find((item) => item.id === id));
  if (sites.length !== total || sites.some((item) => !item)) {
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
          || proxyStore.assignments[String(index + 1)])) {
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
          || proxyStore.assignments[String(index + 1)])) {
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
        : proxyForProfile({ ...row, proxyId: row.proxyId || proxyStore.assignments[String(index + 1)] }, proxyStore);
      let proxyServer = proxyServerUrl(proxy);
      if (proxy && proxy.username) {
        const bridge = await startProxyBridge(proxy);
        newBridges.push({ index: index + 1, bridge });
        proxyServer = bridge.url;
      }
      settings.push({ width, height, scale, proxyServer, proxyLabel: proxyLabel(proxy), bridge:
        newBridges.length && newBridges[newBridges.length - 1].index === index + 1
          ? newBridges[newBridges.length - 1].bridge : null });
    }
  } catch (error) {
    await Promise.all(newBridges.map(({ bridge }) => bridge.close().catch(() => {})));
    return { ok: false, error: error.message || 'Cấu hình proxy không hợp lệ.' };
  }

  const { screen } = require('electron');
  const area = screen.getPrimaryDisplay().workAreaSize;
  const layouts = tileProfileLayouts(settings, area);

  const extras = Array.from(activeProfileIndices).filter((index) => index > total);
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
    offset + 1, layouts[offset], source === 'omni' ? omniDebugPort(omniRows[offset]) : null));

  for (let index = 1; index <= total; index += 1) {
    const previousOmni = activeOmniProfiles.get(index);
    const providerRows = source === 'omni' ? omniRows : hidemiumRows;
    const keep = (source === 'omni' || source === 'hidemium') && previousOmni
      && previousOmni.provider === source && previousOmni.profileId === providerRows[index - 1]
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
    const result = configured[index];
    if (result.status !== 'fulfilled' || !result.value.ok) return { ok: false,
      error: result.status === 'rejected' ? result.reason.message : result.value.error,
      proxy: settings[index].proxyLabel };
    if (source === 'omni' || source === 'hidemium') {
      const providerRows = source === 'omni' ? omniRows : hidemiumRows;
      const previousOmni = activeOmniProfiles.get(index + 1);
      if (previousOmni && (previousOmni.profileId !== providerRows[index] || previousOmni.provider !== source)) {
        await stopOmniProfile(previousOmni);
        activeOmniProfiles.delete(index + 1);
      }
      const omni = source === 'omni' ? await openOmniProfile(apiUrl, providerRows[index])
        : await openHidemiumProfile(apiUrl, providerRows[index]);
      activeOmniProfiles.set(index + 1, omni);
      const attached = await engine.call('chrome.attachExternal', {
        port: omni.port, width: settings[index].width, height: settings[index].height, provider: source,
      }, 45000);
      if (!attached?.ok) {
        await stopOmniProfile(omni);
        activeOmniProfiles.delete(index + 1);
        return { ok: false, error: attached?.error || `Không gắn được Chrome profile ${source === 'omni' ? 'OmniLogin' : 'Hidemium'}.` };
      }
    } else {
      const previousOmni = activeOmniProfiles.get(index + 1);
      if (previousOmni) {
        await stopOmniProfile(previousOmni);
        activeOmniProfiles.delete(index + 1);
      }
    }
    const reply = await engine.call('site.open', { url: sites[index].url }, 45000);
    if ((!reply || !reply.ok) && (source === 'omni' || source === 'hidemium')) {
      const activeOmni = activeOmniProfiles.get(index + 1);
      activeOmniProfiles.delete(index + 1);
      if (activeOmni) await stopOmniProfile(activeOmni);
    }
    return { ...reply, site: sites[index].label,
      proxy: source === 'omni' || source === 'hidemium' ? `Proxy theo cấu hình ${source === 'omni' ? 'OmniLogin' : 'Hidemium'}` : settings[index].proxyLabel,
      width: settings[index].width, height: settings[index].height, scale: settings[index].scale,
      ...(source === 'omni' ? { omni_profile_id: omniRows[index] } : {}),
      ...(source === 'hidemium' ? { hidemium_profile_id: hidemiumRows[index] } : {}) };
  }));

  for (let index = 1; index <= total; index += 1) {
    const result = configured[index - 1];
    const setting = settings[index - 1];
    const openResult = openResults[index - 1];
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
  return { ok: true, count: total, site: sites.map((item) => item.label).join(' / '),
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

ipcMain.handle('app:info', () => ({
  version: app.getVersion(),
  root: PROJECT_ROOT,
  engines: Object.keys(engines),
  profileSites: PROFILE_SITES.map(({ id, label, url }) => ({ id, label, url })),
}));

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
