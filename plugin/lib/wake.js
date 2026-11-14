// Pure helpers for the daily free-time schedule and the messages around it.
// No host dependencies, so they can be unit-tested with `node --test`.
//
// The day has a few free-time slots (by default breakfast, lunch, dinner and a
// maybe-late-evening one). Each slot starts at a random minute inside its
// window, rolled once per day and remembered, and lasts a fixed number of
// minutes. Outside them the resident "just lives" (the house handles that).

/** @typedef {{ name: string, from: string, to: string, minutes: number, chance?: number }} Slot */
/** @typedef {{ name: string, start: number, minutes: number }} Plan  start = epoch ms */

/**
 * "HH:MM" -> minutes after midnight.
 * @param {string} s
 */
export function parseClock(s) {
  const m = /^\s*(\d{1,2}):(\d{2})\s*$/.exec(String(s))
  if (!m) throw new Error(`time must look like "07:30", got "${s}"`)
  const [h, mi] = [Number(m[1]), Number(m[2])]
  if (h > 23 || mi > 59) throw new Error(`time out of range: "${s}"`)
  return h * 60 + mi
}

/**
 * Validate the slot list (throws on a bad entry).
 * @param {Slot[]} slots
 */
export function checkSlots(slots) {
  for (const s of slots) {
    const from = parseClock(s.from)
    const to = parseClock(s.to)
    if (to < from) throw new Error(`slot "${s.name}": "to" (${s.to}) is before "from" (${s.from})`)
    if (!(s.minutes > 0)) throw new Error(`slot "${s.name}": minutes must be positive`)
  }
  return slots
}

/**
 * Roll one day's plan: a start time inside each slot's window, and whether a
 * slot with `chance` < 1 happens at all.
 * @param {Date} day any moment of that (local) day
 * @param {Slot[]} slots
 * @param {() => number} [random]
 * @returns {Plan[]} sorted by start
 */
export function planDay(day, slots, random = Math.random) {
  const midnight = new Date(day.getFullYear(), day.getMonth(), day.getDate())
  const out = []
  for (const s of slots) {
    if (s.chance !== undefined && s.chance < 1 && random() >= s.chance) continue
    const from = parseClock(s.from)
    const to = parseClock(s.to)
    const minute = from + Math.floor(random() * (to - from + 1))
    const start = new Date(midnight)
    start.setMinutes(minute)
    out.push({ name: s.name, start: start.getTime(), minutes: s.minutes })
  }
  return out.sort((a, b) => a.start - b.start)
}

/**
 * The slot to act on: one that is running now (with at least `minMinutes`
 * left), else the next one to come.
 * @param {number} now epoch ms
 * @param {Plan[]} plans
 * @param {number} [minMinutes]
 * @returns {{ plan: Plan, until: number, active: boolean } | undefined}
 */
export function findSlot(now, plans, minMinutes = 5) {
  const sorted = [...plans].sort((a, b) => a.start - b.start)
  for (const p of sorted) {
    const until = p.start + p.minutes * 60_000
    if (p.start <= now && until - now >= minMinutes * 60_000) return { plan: p, until, active: true }
    if (p.start > now) return { plan: p, until, active: false }
  }
  return undefined
}

/** Local calendar date "YYYY-MM-DD". @param {Date} d */
export function localDay(d) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Local "HH:MM". @param {Date | number} d */
export function hhmm(d) {
  const t = new Date(d)
  return `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`
}

/** Human-friendly "3小时20分钟" for a duration. @param {number} ms */
export function formatDuration(ms) {
  const minutes = Math.floor(ms / 60_000)
  if (minutes < 1) return '不到一分钟'
  const d = Math.floor(minutes / 1440)
  const h = Math.floor((minutes % 1440) / 60)
  const m = minutes % 60
  return [d && `${d}天`, h && `${h}小时`, m && `${m}分钟`].filter(Boolean).join('')
}

/** Local wall-clock time "YYYY-MM-DDTHH:MM:SS" (matches the house's event timestamps). @param {Date} d */
export function localIso(d) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${localDay(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** Event kinds too trivial to repeat back to her. */
const RECAP_SKIP = new Set(['move'])

/**
 * Turn the house's resident events into a short recap list.
 * @param {{ kind: string, text: string }[]} events
 */
export function recapEvents(events, max = 10, maxChars = 40) {
  const lines = []
  for (const e of events) {
    // a whole letter read back is too much: the first few words are enough to remember it
    const text = e.text.length > maxChars ? e.text.slice(0, maxChars) + '……' : e.text
    if (RECAP_SKIP.has(e.kind) || lines.includes(text)) continue
    lines.push(text)
  }
  return lines.length > max ? [...lines.slice(0, max - 1), `……等 ${lines.length - max + 1} 件事`] : lines
}

/**
 * The message that opens a free-time slot.
 * @param {{ slotName: string, start: number, until: number, before?: string, recap?: string[],
 *           news: string[], lastNote?: string, look: string, resumed?: boolean }} p
 */
export function buildWakeMessage({ slotName, start, until, before, recap = [], news, lastNote, look, resumed = false }) {
  const minutes = Math.round((until - start) / 60_000)
  const lines = [resumed
    ? `（自由活动时间继续：${slotName}，现在 ${hhmm(start)}，到 ${hhmm(until)} 结束，还有 ${minutes} 分钟。）`
    : `（自由活动时间到了：${slotName}，${hhmm(start)}–${hhmm(until)}，共 ${minutes} 分钟。）`]
  if (before) lines.push(`在这之前，你一直在过平淡的日常——刚才在${before.replace(/^在/, '')}。`)
  if (recap.length) lines.push('上次自由活动的时候，你' + recap.join('；') + '。')
  if (lastNote) lines.push(`日记里最近的一段${lastNote.startsWith('（') ? '' : '：'}${lastNote}`)
  const uniqueNews = [...new Set(news)].slice(-8)
  if (uniqueNews.length) lines.push('这段时间里：' + uniqueNews.join('；') + '。')
  lines.push('', look, '')
  lines.push('这段时间由你自己安排，想做什么都可以，用 house_do 行动。动作会花真实的时间（走路、做饭、打扫……），'
    + 'house_do 等整段脚本做完才给出结果；炖、煮、烤、蒸的菜下锅以后可以先去做别的。')
  lines.push('时间到了，或者你想结束的时候，先用 diary_write 写下这次的日记，再调用 end_free_time。之后你的角色会自己去做一些日常事务，直到下一次自由活动。')
  return lines.join('\n')
}

/**
 * The nudge sent when she ended her turn early but free time is not over.
 * @param {{ left: number, look: string }} p left = minutes
 */
export function buildNudge({ left, look }) {
  return [
    `（过了一会儿。自由活动还剩 ${left} 分钟。）`,
    '',
    look,
    '',
    '想继续做点什么就接着用 house_do；不想了就写下这次的日记（diary_write），再调用 end_free_time。',
  ].join('\n')
}

export const REST_TEXT = '（这次自由活动结束了。接下来你的角色会自己去做一些日常事务，直到下一次自由活动时间。）'
export const OVER_TEXT = '自由活动时间已经结束了，现在不能再行动。请调用 end_free_time。'
export const OVER_DIARY_TEXT = '自由活动时间已经结束了，现在不能再行动。用 diary_write 写下这次的日记，然后调用 end_free_time。'
export const DIARY_FIRST_TEXT = '结束之前，先用 diary_write 写下这次自由活动的日记，写完再调用 end_free_time。'
/** The message sent when free time runs out while she is idle and has not written her diary. */
export const TIME_UP_TEXT = '（自由活动时间到了。用 diary_write 写下这次的日记，然后调用 end_free_time。）'
