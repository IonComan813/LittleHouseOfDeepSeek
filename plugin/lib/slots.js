// The default day (overridable in the plugin config, `wake.slots` and `sleep`).
// Each slot starts at a random minute between `from` and `to` (rolled once a day)
// and lasts `minutes`; a slot with `chance` < 1 only happens on some days.
// She wakes up at the start of the first slot (so the day's first message is
// her morning free time) and goes to bed at a random minute in `sleep`.

export const DEFAULT_SLOTS = [
  { name: '早上', from: '07:30', to: '08:30', minutes: 40 },
  { name: '中午', from: '11:30', to: '12:30', minutes: 40 },
  { name: '傍晚', from: '17:30', to: '18:30', minutes: 40 },
  { name: '晚上', from: '21:30', to: '22:30', minutes: 40 },
]

export const DEFAULT_SLEEP = { from: '23:30', to: '23:59' }
