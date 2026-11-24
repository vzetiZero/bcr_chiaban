// Node test: the incident siren ported from the reference tool.
//
// Rules required by the user:
//  - A siren rings for critical failures (wrong stake, wrong table, stop betting).
//  - Ordinary progress and benign errors stay silent.
//  - It can be disabled and the volume is adjustable and persisted.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(ROOT, 'ui', 'renderer', 'alarm.js'), 'utf8');
const html = fs.readFileSync(path.join(ROOT, 'ui', 'renderer', 'index.html'), 'utf8');
const app = fs.readFileSync(path.join(ROOT, 'ui', 'renderer', 'app.js'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'ui', 'renderer', 'styles.css'), 'utf8');

test('alarm.js exposes a global API for the plain-script renderer', () => {
  assert.match(source, /window\.aibcrAlarm = \{/);
  assert.match(source, /init: initAlarm/);
  assert.match(source, /notify: alarmForMessage/);
});

test('the siren is synthesised with Web Audio, no audio files', () => {
  assert.match(source, /createOscillator/);
  assert.match(source, /createGain/);
  assert.match(source, /sawtooth/);
  assert.doesNotMatch(source, /\.mp3|\.wav|new Audio\(/);
});

test('the siren sweeps frequency like the reference pulses', () => {
  assert.match(source, /850/);
  assert.match(source, /1250/);
  assert.match(source, /1300/);
  assert.match(source, /exponentialRampToValueAtTime/);
});

test('critical incidents are recognised without diacritics', () => {
  assert.match(source, /normalize\('NFD'\)/);
  assert.match(source, /ALARM_PATTERNS_NORMALIZED/);
  for (const phrase of ['lệch tiền', 'lệch bàn', 'không xếp đủ chip', 'dừng cược',
    'từ chối nhận chip', 'vượt quá giới hạn', 'không tìm thấy bàn']) {
    assert.ok(source.includes(phrase), `missing pattern: ${phrase}`);
  }
});

test('only error-level messages are considered', () => {
  assert.match(source, /level \|\| ''\)\.toLowerCase\(\) !== 'error'/);
});

test('repeat sirens are throttled', () => {
  assert.match(source, /ALARM_THROTTLE_MS = 2500/);
  assert.match(source, /now - lastAlarmAt < ALARM_THROTTLE_MS/);
});

test('enable state and volume persist in localStorage', () => {
  assert.match(source, /aibcr\.alarm\.enabled/);
  assert.match(source, /aibcr\.alarm\.volume/);
  assert.match(source, /localStorage\.setItem\(ALARM_STORAGE_KEY/);
  assert.match(source, /localStorage\.setItem\(ALARM_VOLUME_KEY/);
});

test('a missing saved volume does not mute the siren', () => {
  // Number(null) === 0 used to force 0% and silence every alarm.
  assert.match(source, /rawVolume !== null/);
  assert.match(source, /alarmVolume = 0\.8/);
});

test('the UI provides toggle, volume and test controls', () => {
  assert.match(html, /id="alarm-sound-box"/);
  assert.match(html, /id="alarm-toggle"/);
  assert.match(html, /id="alarm-volume"/);
  assert.match(html, /id="alarm-test"/);
  assert.match(html, /id="alarm-state-text"/);
});

test('alarm.js loads before app.js', () => {
  const alarmAt = html.indexOf('src="alarm.js"');
  const appAt = html.indexOf('src="app.js"');
  assert.ok(alarmAt >= 0 && appAt > alarmAt, 'alarm.js must load before app.js');
});

test('the renderer rings the siren from activity log and group status', () => {
  assert.match(app, /window\.aibcrAlarm\?\.notify\?\.\(item\.text, \{ level: item\.level \}\)/);
  assert.match(app, /window\.aibcrAlarm\?\.notify\?\.\(status\.note, \{ level: 'error' \}\)/);
  assert.match(app, /window\.aibcrAlarm\?\.init\?\.\(\)/);
});

test('the alarm box flashes and has a disabled state', () => {
  assert.match(css, /\.alarm-box\.flashing/);
  assert.match(css, /\.alarm-box\.off/);
  assert.match(source, /box\.classList\.toggle\('flashing'/);
});

test('the jump from the info path cannot ring', () => {
  const notify = source.slice(source.indexOf('function alarmForMessage'));
  const body = notify.slice(0, notify.indexOf('function initAlarm'));
  assert.match(body, /return false/);
  assert.match(body, /level/);
});

test('a captcha that needs the operator rings the siren', () => {
  // Rule from the user: never solve the slider, but make noise and wait.
  assert.ok(source.includes("'xác minh an toàn'"), 'missing captcha pattern');
  assert.ok(source.includes("'kéo thanh trượt'"), 'missing slider pattern');
  assert.match(source, /actionLevel/);
  assert.match(source, /=== 'action'/);
});

test('the group flow raises the siren when a DG lobby is captcha-blocked', () => {
  const main = fs.readFileSync(path.join(ROOT, 'ui', 'main.js'), 'utf8');
  // Both deadlocks of the group run must surface as `error` so app.js rings.
  assert.match(main, /captchaNote/);
  assert.match(main, /xác minh an toàn\|kéo thanh trượt/i);
  assert.match(main, /error: Boolean\(captchaNote\)/);
  assert.match(main, /error: waitCaptcha/);
});

test('an action-level log row is styled apart from an error', () => {
  assert.match(css, /\.activity-log-row\.action/);
  const renderer = fs.readFileSync(path.join(ROOT, 'ui', 'renderer', 'app.js'), 'utf8');
  assert.match(renderer, /item\.level === 'action'/);
});

test('the main process lets an action-level log reach the renderer intact', () => {
  // Bug measured while wiring the captcha alarm: `appendActivityLog` folded
  // every level except `error` into `info`, so a captcha line could neither be
  // styled as an action nor ring the siren. The funnel must carry it through
  // to disk *and* to `activity-log:entry`.
  const main = fs.readFileSync(path.join(ROOT, 'ui', 'main.js'), 'utf8');
  const body = main.slice(main.indexOf('function appendActivityLog'));
  const logBody = body.slice(0, body.indexOf('const PYTHON_CANDIDATES'));
  assert.match(logBody, /\['error', 'action'\]\.includes\(level\)/);
  assert.doesNotMatch(logBody, /level === 'error' \? 'error' : 'info'/);
});
