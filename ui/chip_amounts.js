'use strict';

function reachableAmounts(limit, denominations) {
  const reachable = new Uint8Array(limit + 1);
  reachable[0] = 1;
  const values = [...new Set((denominations || []).map(Number)
    .filter((value) => Number.isInteger(value) && value > 0 && value <= limit))];
  for (let amount = 1; amount <= limit; amount += 1) {
    for (const value of values) {
      if (value <= amount && reachable[amount - value]) {
        reachable[amount] = 1;
        break;
      }
    }
  }
  return reachable;
}

function commonReachableStake(target, states) {
  const cap = Math.trunc(Number(target));
  if (!Number.isInteger(cap) || cap <= 0 || !Array.isArray(states) || !states.length) return 0;
  const lowerBound = Math.max(1, ...states.map((state) => Math.max(0, Math.ceil(Number(state?.min_k) || 0))));
  const upperBound = Math.min(cap, ...states.map((state) => {
    const max = Math.floor(Number(state?.max_k) || 0);
    // ``balance_k`` = 0 nghĩa là "chưa đọc được số dư" chứ không phải "hết tiền":
    // đo trên bàn 60101, ``playerInfo.balance`` trả 0 trong khi bàn in "Balance
    // 0.00". Chỉ khi adapter báo đã đọc được số dư thật (``balance_known``) mới lấy
    // số dư làm trần, nếu không sẽ chặn cược oan về mức 1k.
    const known = state?.balance_known === true;
    const balance = known ? Math.floor(Number(state?.balance_k) || 0) : 0;
    return Math.min(max || cap, balance || cap);
  }));
  if (lowerBound > upperBound) return 0;
  const reachable = states.map((state) => reachableAmounts(upperBound, state?.denominations_k));
  for (let amount = upperBound; amount >= lowerBound; amount -= 1) {
    if (reachable.every((values) => values[amount])) return amount;
  }
  return 0;
}

module.exports = { commonReachableStake };
