// Her long-term memory (M4): pure functions, no host dependencies.
//
// Once a day a separate summarising session (no persona, no tools) reads the
// day's whole session (free time, phone, bedtime), her diary and her current
// memory and answers in JSON; this
// module folds that answer in, lets memories fade with time, and renders the
// text that opens each day's session.
//
//   items: { id, kind: 'day' | 'event' | 'plan', day, text, importance, seen }
//     day    one summary per day ("最近的日子"), ordinary life included
//     event  something important she must not forget ("记得的事": promises,
//            the owner's habits, big firsts) — not the day's ordinary events
//     plan   something she wants to do (fades faster; dropped once done)
//   people: { name: { note, day } }
//
// Fading (after surfcore's memory card): by days since the memory was last
// seen (written or recalled), one step at a time — 清晰 → 清楚 → 模糊 →
// 只剩印象 → forgotten. Important memories last longer; importance ≥ 90 is
// never forgotten. Forgotten items leave the card but stay in the archive.

export const CLARITY = ['vivid', 'clear', 'fuzzy', 'trace', 'forgotten']
export const MAX_SUMMARY_CHARS = 600
export const MAX_ITEM_CHARS = 120

/** Whole days from `from` to `to` (YYYY-MM-DD). */
export function daysBetween(from, to) {
  return Math.round((Date.parse(to + 'T12:00:00Z') - Date.parse(from + 'T12:00:00Z')) / 86_400_000)
}

/**
 * How clear a memory is on `today`.
 * @param {{ kind: string, importance: number, seen: string }} item @param {string} today
 */
export function clarity(item, today) {
  const age = daysBetween(item.seen, today)
  const imp = Math.max(1, Math.min(100, Number(item.importance) || 30))
  const k = item.kind === 'plan' ? 0.5 : 1
  let c
  if (age <= 2) c = 'vivid'
  else if (age <= (5 + imp / 10) * k) c = 'clear'
  else if (age <= (10 + imp / 4) * k) c = 'fuzzy'
  else if (age <= (20 + imp / 2) * k) c = 'trace'
  else c = 'forgotten'
  if (imp >= 90 && CLARITY.indexOf(c) > CLARITY.indexOf('fuzzy')) c = 'fuzzy'
  return c
}

/** A memory's text as she remembers it now. */
export function fade(text, c) {
  const chars = [...text]
  if (c === 'fuzzy') return chars.slice(0, Math.max(8, Math.ceil(chars.length * 0.6))).join('') + '……（记不太清了）'
  if (c === 'trace') return chars.slice(0, 10).join('') + '……（只剩一点印象）'
  return text
}

export function emptyMemory() {
  return { version: 1, nextId: 1, doneDays: [], items: [], people: {} }
}

/** Pull the first JSON object out of a model reply (it may be wrapped in ```json). */
export function parseReply(text) {
  const s = String(text ?? '')
  const start = s.indexOf('{')
  const end = s.lastIndexOf('}')
  if (start < 0 || end <= start) throw new Error('no JSON object in the reply')
  return JSON.parse(s.slice(start, end + 1))
}

const clip = (t, n) => {
  const chars = [...String(t ?? '').trim().replace(/\s+/g, ' ')]
  return chars.length > n ? chars.slice(0, n).join('') + '……' : chars.join('')
}

/**
 * Fold one day's summary into the memory (returns a new object; `archive` gets the new items).
 * @param {ReturnType<typeof emptyMemory>} mem
 * @param {string} day
 * @param {{ summary?: string, plans?: string[], memories?: {text: string, importance?: number}[],
 *           people?: Record<string, string>, recalled?: string[], done?: string[] }} reply
 * @returns {{ mem: ReturnType<typeof emptyMemory>, added: object[] }}
 */
export function mergeDay(mem, day, reply) {
  const out = structuredClone(mem)
  const added = []
  const add = (kind, text, importance) => {
    const t = clip(text, kind === 'day' ? MAX_SUMMARY_CHARS : MAX_ITEM_CHARS)
    if (!t) return
    const item = { id: `m${out.nextId++}`, kind, day, text: t, importance: Math.max(1, Math.min(100, Math.round(Number(importance) || 30))), seen: day }
    out.items.push(item)
    added.push(item)
  }
  const done = new Set((reply.done ?? []).map(String))
  out.items = out.items.filter((i) => !(i.kind === 'plan' && done.has(i.id)))
  for (const id of reply.recalled ?? []) {
    const it = out.items.find((i) => i.id === String(id))
    if (it && daysBetween(it.seen, day) > 0) it.seen = day
  }
  if (reply.summary) add('day', reply.summary, 50)
  for (const p of reply.plans ?? []) add('plan', typeof p === 'string' ? p : p?.text, typeof p === 'string' ? 40 : p?.importance ?? 40)
  for (const m of reply.memories ?? []) add('event', typeof m === 'string' ? m : m?.text, typeof m === 'string' ? 40 : m?.importance)
  for (const [name, note] of Object.entries(reply.people ?? {})) {
    if (name && note) out.people[clip(name, 20)] = { note: clip(note, MAX_ITEM_CHARS), day }
  }
  if (!out.doneDays.includes(day)) out.doneDays = [...out.doneDays, day].sort().slice(-60)
  return { mem: out, added }
}

/** Drop what is forgotten by `today` (they stay in the archive). */
export function forget(mem, today) {
  return { ...mem, items: mem.items.filter((i) => clarity(i, today) !== 'forgotten') }
}

const md = (day) => day.slice(5)

/**
 * The memory as she reads it at the start of a day.
 * @param {ReturnType<typeof emptyMemory>} mem @param {string} today
 * @param {{ ids?: boolean }} [opts] ids: show [m12] for the summariser
 */
export function render(mem, today, opts = {}) {
  const live = mem.items
    .map((i) => ({ ...i, c: clarity(i, today) }))
    .filter((i) => i.c !== 'forgotten')
    .sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : 0))
  const line = (i) => `- ${opts.ids ? `[${i.id}] ` : ''}${md(i.day)}：${fade(i.text, i.c)}`
  const sections = []
  const days = live.filter((i) => i.kind === 'day').slice(0, 7)
  if (days.length) sections.push('### 最近的日子', ...days.map(line))
  const plans = live.filter((i) => i.kind === 'plan')
  if (plans.length) sections.push('### 想做的事', ...plans.map(line))
  const events = live.filter((i) => i.kind === 'event').sort((a, b) => b.importance - a.importance || (a.day < b.day ? 1 : -1)).slice(0, 30)
  if (events.length) sections.push('### 记得的事', ...events.map(line))
  const people = Object.entries(mem.people)
  if (people.length) sections.push('### 认识的人', ...people.map(([n, p]) => `- ${n}：${p.note}`))
  return sections.join('\n')
}

/** The summariser's instructions for one day. */
export function buildSummaryPrompt({ name, day, memoryText, diary, transcript = '', chats = '' }) {
  return [
    `下面是${name}（日记和对话里的「我」/「她」）在 ${day} 这一天的完整记录：她这一天的对话（自由活动里在小屋做的事、手机上的 QQ 聊天、睡前整理日记），她的日记，以及她现在的记忆。请整理这一天，用于更新她的长期记忆。`,
    '日记是她自己挑出来想记住的事，最重要；对话记录用来补充细节和日记里没写的事（比如聊天里说过的话、答应别人的事）。',
    '',
    '## 她现在的记忆（方括号里是编号）',
    memoryText || '（还没有）',
    '',
    `## ${day} 的日记`,
    diary || '（这天没有日记）',
    '',
    ...(transcript ? [`## ${day} 的对话记录`, transcript] : [`## ${day} 的 QQ 聊天`, chats || '（这天没有聊天）']),
    '',
    '## 输出',
    '只输出一个 JSON 对象，不要别的文字：',
    '{',
    '  "summary": "第一人称（我）写这一天：先写最重要的事和心情；篇幅允许的话，平凡的日常也可以写一些（做了什么饭、天气、团子），四到八句；不要以「这一天」开头",',
    '  "plans": ["想做的事、打算、没做完的事，第一人称，一条一句。日记和对话里提到的都要列上（包括答应别人的事）；已经做完的不要列；现有记忆里已有的不要重复"],',
    '  "memories": [{"text": "不能忘的重要的事，第一人称一句话", "importance": 80到100}],',
    '  "people": {"名字": "对这个人的印象、他的习惯和喜好、最近和他有关的事，一两句（会替换旧的）"},',
    '  "recalled": ["这一天又提到或想起的旧记忆的编号，如 m3"],',
    '  "done": ["「想做的事」里这一天已经做到了的编号"]',
    '}',
    'memories 只放**重要、不能忘**的事：和别人的约定、主人的习惯和喜好、很重要的第一次、改变生活的大事。平常的事写进 summary，不要放进 memories。大多数日子是 0 条，最多 3 条。',
    '只根据上面的内容，不要编造。',
  ].join('\n')
}

/** Day-session transcript lines (transcripts/<day>.jsonl) as readable text. */
export function formatTranscript(entries) {
  return entries
    .filter((e) => e && e.text)
    .map((e) => {
      if (e.who === 'in') return `[${e.t}] 消息：${e.text}`
      if (e.who === 'she') return `[${e.t}] 她：${e.text}`
      if (e.who === 'call') return `[${e.t}] 她用了 ${e.tool}：${e.text}`
      return `  → ${e.text.replace(/\n/g, '\n    ')}`
    })
    .join('\n')
}

/** QQ transcript lines (qq/<day>.jsonl entries) as readable text. */
export function formatChats(entries, ownerName = '主人') {
  return entries
    .filter((e) => e && e.text)
    .map((e) => {
      const t = String(e.t ?? '').slice(11, 16)
      const who = e.out ? '她' : e.name || ownerName
      return `${t} ${who}${e.proactive ? '（主动发的）' : ''}：${e.text}`
    })
    .join('\n')
}
