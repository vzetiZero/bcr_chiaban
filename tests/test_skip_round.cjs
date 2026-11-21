// Node test: a failed hand is skipped, the session keeps running.
//
// The user requires that when one hand cannot be staged (for example a zero
// balance demo account), the group must NOT stop: it abandons that hand and
// attempts the next logical hand instead.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'ui', 'main.js'), 'utf8');

function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} not found`);
  let depth = 0;
  let i = source.indexOf('{', start);
  const from = i;
  for (; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  return source.slice(start, i + 1);
}

test('there is a skip helper that keeps the session active', () => {
  const skip = extract('skipGroupRound');
  assert.match(skip, /skippedRound/);
  assert.match(skip, /skippedCount/);
  assert.doesNotMatch(skip, /active = false/);
  assert.doesNotMatch(skip, /clearInterval/);
});

test('a chip-ladder failure skips the hand instead of stopping', () => {
  const tick = extract('groupBettingTick');
  const chipBlock = tick.slice(tick.indexOf('commonReachableStake'));
  assert.match(chipBlock, /skipGroupRound\(roundId/);
  assert.doesNotMatch(chipBlock.slice(0, 1400), /stopGroupBetting\(`Kh\\u00f4ng c\\u00f3 m/);
});

test('an incomplete chip placement skips the hand instead of stopping', () => {
  const tick = extract('groupBettingTick');
  const branch = tick.slice(tick.indexOf('if (!replies.every((reply) => reply?.ok && reply.staged))'));
  const branchEnd = branch.indexOf('groupBetting.lastPlaced = {');
  assert.ok(branchEnd > 0, 'placement branch not found');
  const body = branch.slice(0, branchEnd);
  assert.ok(body.includes('skipGroupRound(roundId'), 'expected skipGroupRound in branch');
  assert.ok(!body.includes('stopGroupBetting'), 'branch must not stop the group');
});

test('a skipped round is not retried in the same hand', () => {
  const tick = extract('groupBettingTick');
  assert.match(tick, /skippedRound === roundId/);
  assert.match(tick, /Tay \$\{roundId\} \u0111\u00e3 b\u1ecf qua/);
});

test('the skip state resets for a new round id', () => {
  const tick = extract('groupBettingTick');
  assert.match(tick, /groupBetting\.skippedRound = ''/);
});

test('structural problems still stop the group', () => {
  const tick = extract('groupBettingTick');
  // Closed profiles, changed tables and mismatched round ids remain hard stops.
  assert.match(tick, /Danh s\u00e1ch profile \u0111\u00e3 \u0111\u1ed5i/);
  assert.match(tick, /Ch\u1ec9 m\u1ed9t ph\u1ea7n profile x\u00e1c nh\u1eadn/);
  assert.match(tick, /Kh\u00f4ng x\u00e1c nh\u1eadn \u0111\u01b0\u1ee3c k\u1ebft qu\u1ea3 v\u00e1n tr\u01b0\u1edbc/);
});

test('skip state is initialised when the group starts', () => {
  const start = extract('startGroupBetting');
  assert.match(start, /skippedRound: ''/);
  assert.match(start, /skippedCount: 0/);
});
