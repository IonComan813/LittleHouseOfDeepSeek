import assert from 'node:assert/strict'
import test from 'node:test'

import { buildSummaryPrompt, clarity, emptyMemory, fade, forget, formatChats, formatTranscript, mergeDay, parseReply, render } from '../lib/memory.js'

const reply = {
  summary: '今天第一次钓到了鲈鱼，团子很黏我。',
  plans: ['明天去沙滩捡贝壳', { text: '攒钱买台灯', importance: 50 }],
  memories: [{ text: '第一次钓到鲈鱼', importance: 85 }, { text: '给绿萝浇了水', importance: 20 }],
  people: { 主人: '下午发来一张小屋的照片，夸我拍得好。' },
}

test('mergeDay adds the day, plans, memories and people', () => {
  const { mem, added } = mergeDay(emptyMemory(), '2026-11-14', reply)
  assert.equal(added.length, 5)
  assert.deepEqual(mem.items.map((i) => i.kind), ['day', 'plan', 'plan', 'event', 'event'])
  assert.equal(mem.people.主人.note, '下午发来一张小屋的照片，夸我拍得好。')
  assert.deepEqual(mem.doneDays, ['2026-11-14'])
  const text = render(mem, '2026-11-15')
  for (const part of ['### 最近的日子', '### 想做的事', '- 11-14：明天去沙滩捡贝壳', '### 记得的事', '### 认识的人', '- 主人：']) {
    assert.ok(text.includes(part), part)
  }
  assert.ok(render(mem, '2026-11-15', { ids: true }).includes('[m2] 11-14：明天去沙滩捡贝壳'))
})

test('plans can be done; old memories can be recalled', () => {
  let { mem } = mergeDay(emptyMemory(), '2026-11-01', reply)
  mem = mergeDay(mem, '2026-11-12', { summary: '去了沙滩。', done: ['m2'], recalled: ['m4'] }).mem
  assert.ok(!mem.items.some((i) => i.id === 'm2'))
  assert.equal(mem.items.find((i) => i.id === 'm4').seen, '2026-11-12')
})

test('memories fade one step at a time and are forgotten', () => {
  const item = (importance, kind = 'event') => ({ kind, importance, seen: '2026-11-01' })
  assert.equal(clarity(item(40), '2026-11-02'), 'vivid')
  assert.equal(clarity(item(40), '2026-11-08'), 'clear')
  assert.equal(clarity(item(40), '2026-11-15'), 'fuzzy')
  assert.equal(clarity(item(40), '2026-11-30'), 'trace')
  assert.equal(clarity(item(40), '2026-12-30'), 'forgotten')
  assert.equal(clarity(item(40, 'plan'), '2026-11-15'), 'trace') // plans fade faster
  assert.equal(clarity(item(95), '2027-11-01'), 'fuzzy') // very important: never forgotten
  assert.equal(fade('第一次钓到鲈鱼的那天下午', 'trace'), '第一次钓到鲈鱼的那天……（只剩一点印象）')
  const { mem } = mergeDay(emptyMemory(), '2026-11-01', reply)
  assert.equal(forget(mem, '2027-03-01').items.length, 0)
})

test('parseReply finds the JSON in a fenced answer', () => {
  assert.deepEqual(parseReply('```json\n{"summary": "好"}\n```'), { summary: '好' })
  assert.throws(() => parseReply('没有'))
})

test('the summary prompt and chat lines', () => {
  const chats = formatChats([
    { t: '2026-11-14T10:07:00Z', name: '主人', text: '在吗' },
    { t: '2026-11-14T10:08:00Z', out: true, text: '在呀' },
  ])
  assert.equal(chats, '10:07 主人：在吗\n10:08 她：在呀')
  const p = buildSummaryPrompt({ name: '她', day: '2026-11-14', memoryText: '', diary: '日记', chats })
  assert.ok(p.includes('"plans"') && p.includes('2026-11-14 的日记') && p.includes('10:07 主人：在吗'))
})

test('the day session as a transcript for the summariser', () => {
  const t = formatTranscript([
    { t: '11:27', who: 'in', text: '（手机响了，是 QQ 消息：）\n主人：帮我浇花' },
    { t: '11:27', who: 'call', tool: 'house_do', text: '{"script":"water(绿萝)"}' },
    { t: '11:27', who: 'result', text: '✓ water(绿萝)\n  浇好了' },
  ])
  assert.equal(t, '[11:27] 消息：（手机响了，是 QQ 消息：）\n主人：帮我浇花\n[11:27] 她用了 house_do：{"script":"water(绿萝)"}\n  → ✓ water(绿萝)\n      浇好了')
  const p = buildSummaryPrompt({ name: '她', day: '2026-11-14', memoryText: '', diary: '日记', transcript: t })
  assert.ok(p.includes('2026-11-14 的对话记录') && p.includes('不能忘'))
})
