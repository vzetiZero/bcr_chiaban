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
