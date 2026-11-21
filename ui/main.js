// Electron main: cửa sổ + quản lý engine Python riêng cho từng trò.
// Mỗi trò = một tiến trình python riêng (profile Chrome + cổng CDP + file cấu hình riêng),
// nên thao tác ở tab này không ảnh hưởng tab kia.
const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const { randomUUID } = require('node:crypto');
const { parseProxy, proxyLabel, startProxyBridge, checkProxy } = require('./proxy_bridge');

const PROJECT_ROOT = path.resolve(__dirname, '..');
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
  constructor(game, profileIndex = 1, layout = null) {
    this.game = game;
    this.profileIndex = profileIndex;
    this.layout = layout;
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
      '--cdp-port', String(9222 + this.profileIndex - 1),
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
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('engine:event', { game: this.game, event, data });
    }
    if (event === 'state') observeSharedHop(this.profileIndex, data);
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
let sharedHop = null;

function configuredHopRounds(value) {
  const rounds = String(value || '2').trim().split(/[\s,-]+/)
    .map((part) => Number(part)).filter((number) => Number.isInteger(number) && number > 0);
  return rounds.length ? rounds : [2];
}

function sendHopStatus(payload) {
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
    profileEngine(index).call('febet.syncTable', { table_id: target }, 180000)));
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
  sharedHop.since = Date.now() / 1000;
  sharedHop.pending.clear();
  sharedHop.counted.clear();
  sendHopStatus({ active: true, table_id: target, hops: sharedHop.hops,
    note: `Cả ${indices.length} profile đã cùng vào bàn ${target}.` });
}

function observeSharedHop(profileIndex, state) {
  if (!sharedHop || !sharedHop.active || sharedHop.busy
      || !sharedHop.indices.includes(profileIndex) || !state || !Array.isArray(state.history)) return;
  for (const entry of state.history) {
    if (!entry || Number(entry.time) < sharedHop.since || !entry.hand
        || !['B', 'P', 'T'].includes(String(entry.result || '').toUpperCase())) continue;
    const signature = `${entry.table || ''}|${entry.hand}|${String(entry.result).toUpperCase()}`;
    if (sharedHop.counted.has(signature)) continue;
    if (!sharedHop.pending.has(signature)) sharedHop.pending.set(signature, new Map());
    sharedHop.pending.get(signature).set(profileIndex, entry);
    const confirmations = sharedHop.pending.get(signature);
    if (sharedHop.indices.some((index) => !confirmations.has(index))) continue;
    sharedHop.counted.add(signature);
    sharedHop.rounds += 1;
    for (const result of confirmations.values()) {
      sharedHop.totalWagered += Math.max(0, Number(result.stake) || 0);
    }
    if (!sharedHop.targetNotified && sharedHop.config.total_bet > 0
        && sharedHop.totalWagered >= sharedHop.config.total_bet) {
      sharedHop.targetNotified = true;
      sendHopStatus({ active: true, table_id: sharedHop.tableId, hops: sharedHop.hops,
        total_bet: sharedHop.totalWagered, target_bet: sharedHop.config.total_bet,
        note: `Đã đạt mục tiêu doanh số cược ${sharedHop.totalWagered}/${sharedHop.config.total_bet}.` });
    }
    const threshold = sharedHop.schedule[sharedHop.hops % sharedHop.schedule.length];
    sendHopStatus({ active: true, table_id: sharedHop.tableId, rounds: sharedHop.rounds,
      hops: sharedHop.hops, total_bet: sharedHop.totalWagered, target_bet: sharedHop.config?.total_bet,
      note: `Đã xác nhận ${sharedHop.rounds}/${threshold} ván chung.` });
    if (sharedHop.rounds >= threshold) void rotateSharedProfiles();
  }
}

function profileEngine(index) {
  return engines[index === 1 ? 'baccarat' : `baccarat-profile-${index}`];
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

function profileLayout(index, count, width, height, area) {
  const columns = Math.ceil(Math.sqrt(count));
  const column = (index - 1) % columns;
  const row = Math.floor((index - 1) / columns);
  return {
    width, height,
    left: Math.max(0, Math.min(area.width - width, column * (width + 12))),
    top: Math.max(0, Math.min(area.height - height, row * (height + 12))),
  };
}

ipcMain.handle('profile:open', async (_event, { index, count, profile, url }) => {
  const profileIndex = Math.trunc(Number(index));
  if (!Number.isInteger(profileIndex) || profileIndex < 1 || profileIndex > 8) {
    return { ok: false, error: 'Profile không hợp lệ.' };
  }
  if (!PROFILE_SITES.some((site) => site.url === url)) {
    return { ok: false, error: 'Hãy chọn một website hợp lệ trước khi mở profile.' };
  }
  const row = profile || {};
  const width = Math.max(520, Math.min(3840, Math.round(Number(row.width) || 900)));
  const height = Math.max(200, Math.min(2160, Math.round(Number(row.height) || 1200)));
  const scale = Math.max(50, Math.min(200, Math.round(Number(row.scale) || 60)));
  let proxy;
  let newBridge = null;
  try {
    const proxyStore = await loadProxyStore();
    proxy = proxyForProfile({ ...row, proxyId: row.proxyId || proxyStore.assignments[String(profileIndex)] }, proxyStore);
    let proxyServer = proxyServerUrl(proxy);
    if (proxy && proxy.username) {
      newBridge = await startProxyBridge(proxy);
      proxyServer = newBridge.url;
    }
    const { screen } = require('electron');
    const layout = profileLayout(profileIndex, Math.max(1, Math.min(8, Number(count) || profileIndex)),
      width, height, screen.getPrimaryDisplay().workAreaSize);
    const game = profileIndex === 1 ? 'baccarat' : `baccarat-profile-${profileIndex}`;
    if (!engines[game]) engines[game] = new Engine(game, profileIndex, layout);
    const engine = engines[game];
    engine.layout = layout;
    const configured = await engine.call('profile.configure', {
      url, proxy_server: proxyServer, width, height, scale, left: layout.left, top: layout.top,
    });
    if (!configured || !configured.ok) {
      if (newBridge) await newBridge.close().catch(() => {});
      return { ok: false, error: (configured && configured.error) || 'Không áp dụng được cấu hình profile.' };
    }
    await closeProfileBridge(profileIndex);
    const opened = await engine.call('chrome.open');
    if (!opened || !opened.ok) {
      if (newBridge) await newBridge.close().catch(() => {});
      activeProfileIndices.delete(profileIndex);
      return { ok: false, error: (opened && opened.error) || 'Không mở được Chrome.' };
    }
    if (newBridge) activeProxyBridges.set(profileIndex, newBridge);
    activeProfileIndices.add(profileIndex);
    return { ok: true, note: 'Đang mở Chrome profile.', proxy: proxyLabel(proxy), width, height, scale };
  } catch (error) {
    if (newBridge) await newBridge.close().catch(() => {});
    return { ok: false, error: error.message || 'Không mở được Chrome profile.' };
  }
});

ipcMain.handle('febet:open-dg', async (_event) => {
  const indices = Array.from(activeProfileIndices).sort((a, b) => a - b);
  if (!indices.length) return { ok: false, error: 'Hãy mở các profile ở sảnh FEBET trước.' };
  const results = await Promise.allSettled(indices.map((index) =>
    profileEngine(index).call('febet.openDG', {}, 360000)));
  return { ok: true, count: indices.length, replies: results.map((result, offset) =>
    result.status === 'fulfilled' ? { index: indices[offset], ...result.value }
      : { index: indices[offset], ok: false, error: result.reason.message }) };
});

ipcMain.handle('febet:tables', async () => {
  const indices = Array.from(activeProfileIndices).sort((a, b) => a - b);
  if (!indices.length) return { ok: false, error: 'Chưa có profile nào đang mở.' };
  const leader = profileEngine(indices[0]);
  try {
    const current = await leader.call('febet.table', {}, 30000);
    if (current && current.ok && current.in_table && /^60\d{3,}$/.test(String(current.table_id || ''))) {
      return { ok: true, tables: [{ table_id: current.table_id,
        name: current.label || `Bàn ${current.table_id}`, online: 0 }], current_table: true };
    }
    const result = await leader.call('febet.tables', {}, 60000);
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
      const read = await leader.call('febet.table', {}, 30000);
      if (read && read.ok && read.in_table && /^60\d{3,}$/.test(String(read.table_id || ''))) {
        target = String(read.table_id);
      } else {
        const scan = await leader.call('febet.tables', {}, 60000);
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
    profileEngine(index).call('febet.syncTable', { table_id: target }, 180000)));
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
  }
  return { ok: failed === 0, count: indices.length, stake: ladderStake(config),
    config, replies, error: failed ? `${failed} profile không nhận được cấu hình dãy cược.` : '' };
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
    width: 1180,
    height: 800,
    minWidth: 1000,
    minHeight: 680,
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

ipcMain.handle('profiles:open', async (_event, { count, siteId, profiles }) => {
  const total = Math.max(1, Math.min(8, Math.trunc(Number(count) || 1)));
  const site = PROFILE_SITES.find((item) => item.id === siteId);
  if (!site) return { ok: false, error: 'Hãy chọn một site trong danh sách.' };
  const requested = Array.isArray(profiles) ? profiles : [];
  const proxyStore = await loadProxyStore();
  const settings = [];
  const newBridges = [];
  try {
    for (let index = 0; index < total; index += 1) {
      const row = requested[index] || {};
      const width = Math.max(520, Math.min(3840, Math.round(Number(row.width) || 900)));
      const height = Math.max(200, Math.min(2160, Math.round(Number(row.height) || 1200)));
      const scale = Math.max(50, Math.min(200, Math.round(Number(row.scale) || 60)));
      const proxy = proxyForProfile({ ...row, proxyId: row.proxyId || proxyStore.assignments[String(index + 1)] }, proxyStore);
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
  const columns = Math.ceil(Math.sqrt(total));
  const rows = Math.ceil(total / columns);
  const columnWidths = Array(columns).fill(0);
  const rowHeights = Array(rows).fill(0);
  settings.forEach((item, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    columnWidths[column] = Math.max(columnWidths[column], item.width);
    rowHeights[row] = Math.max(rowHeights[row], item.height);
  });
  const gap = 12;
  const gridWidth = columnWidths.reduce((sum, width) => sum + width, 0) + gap * (columns - 1);
  const gridHeight = rowHeights.reduce((sum, height) => sum + height, 0) + gap * (rows - 1);
  const startX = Math.max(0, Math.floor((area.width - gridWidth) / 2));
  const startY = Math.max(0, Math.floor((area.height - gridHeight) / 2));
  const layouts = settings.map((item, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    const left = startX + columnWidths.slice(0, column).reduce((sum, width) => sum + width + gap, 0);
    const top = startY + rowHeights.slice(0, row).reduce((sum, height) => sum + height + gap, 0);
    return { ...item, left, top };
  });

  const extras = Array.from(activeProfileIndices).filter((index) => index > total);
  if (extras.length) {
    const closeResults = await Promise.allSettled(extras.map(async (index) => {
      const engine = profileEngine(index);
      if (engine) await engine.call('profile.configure', { close: true });
      await closeProfileBridge(index);
      activeProfileIndices.delete(index);
    }));
    if (closeResults.some((item) => item.status === 'rejected')) {
      await Promise.all(newBridges.map(({ bridge }) => bridge.close().catch(() => {})));
      return { ok: false, error: 'Không đóng được các profile dư.' };
    }
  }

  const started = [];
  for (let i = 1; i <= total; i += 1) {
    const game = i === 1 ? 'baccarat' : `baccarat-profile-${i}`;
    if (!engines[game]) engines[game] = new Engine(game, i, layouts[i - 1]);
    engines[game].layout = layouts[i - 1];
    started.push(engines[game]);
  }

  const configured = await Promise.allSettled(started.map((engine, index) => engine.call('profile.configure', {
    url: site.url,
    proxy_server: layouts[index].proxyServer,
    width: layouts[index].width,
    height: layouts[index].height,
    scale: layouts[index].scale,
    left: layouts[index].left,
    top: layouts[index].top,
  })));
  const openResults = await Promise.allSettled(started.map((engine, index) => {
    const result = configured[index];
    if (result.status !== 'fulfilled' || !result.value.ok) {
      return Promise.resolve({ ok: false,
        error: result.status === 'rejected' ? result.reason.message : result.value.error,
        proxy: settings[index].proxyLabel });
    }
    return engine.call('site.open', { url: site.url }).then((reply) => ({
      ...reply, proxy: settings[index].proxyLabel, width: settings[index].width,
      height: settings[index].height, scale: settings[index].scale,
    }));
  }));

  for (let index = 1; index <= total; index += 1) {
    const result = configured[index - 1];
    const setting = settings[index - 1];
    if (result.status === 'fulfilled' && result.value.ok) {
      await closeProfileBridge(index);
      if (setting.bridge) activeProxyBridges.set(index, setting.bridge);
      activeProfileIndices.add(index);
    } else if (setting.bridge) {
      await setting.bridge.close().catch(() => {});
      activeProfileIndices.delete(index);
    }
  }
  const replies = openResults.map((result, index) => result.status === 'fulfilled'
    ? result.value : { ok: false, error: result.reason.message, proxy: settings[index].proxyLabel });
  return { ok: true, count: total, site: site.label, replies };
});

ipcMain.handle('profiles:close', async () => {
  const indices = Array.from(activeProfileIndices);
  const targets = indices.map((index) => ({ index, engine: profileEngine(index) })).filter((item) => item.engine);
  const replies = await Promise.allSettled(targets.map(({ engine }) => engine.call('profile.configure', { close: true })));
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
