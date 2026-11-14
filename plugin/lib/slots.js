// The default daily free-time slots (overridable in the plugin config, `wake.slots`).
// Each one starts at a random minute between `from` and `to` (rolled once a day)
// and lasts `minutes`; a slot with `chance` < 1 only happens on some days.

export const DEFAULT_SLOTS = [
  { name: '早上', from: '07:30', to: '08:30', minutes: 40 },
  { name: '中午', from: '11:30', to: '12:30', minutes: 40 },
  { name: '傍晚', from: '17:30', to: '18:30', minutes: 40 },
  { name: '深夜', from: '21:30', to: '22:30', minutes: 40, chance: 0.5 },
]
