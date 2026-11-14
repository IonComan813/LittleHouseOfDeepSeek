import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  buildNudge, planBed, buildWakeMessage, checkSlots, findSlot, formatDuration, hhmm, localIso, parseClock, planDay, recapEvents,
} from '../lib/wake.js'
import { DEFAULT_SLEEP, DEFAULT_SLOTS } from '../lib/slots.js'

const at = (h, m) => new Date(2026, 10, 13, h, m, 0, 0).getTime()

test('parseClock', () => {
  assert.equal(parseClock('07:30'), 450)
  assert.equal(parseClock('7:05'), 425)
  assert.throws(() => parseClock('7'))
  assert.throws(() => parseClock('25:00'))
})

test('checkSlots rejects a backwards window', () => {
  assert.doesNotThrow(() => checkSlots(DEFAULT_SLOTS))
  assert.throws(() => checkSlots([{ name: 'x', from: '09:00', to: '08:00', minutes: 40 }]))
})

test('planDay rolls a start inside each window', () => {
  const day = new Date(2026, 10, 13, 15, 0)
  const low = planDay(day, DEFAULT_SLOTS, () => 0)
  assert.deepEqual(low.map((p) => [p.name, hhmm(p.start), p.minutes]), [
    ['早上', '07:30', 40], ['中午', '11:30', 40], ['傍晚', '17:30', 40], ['晚上', '21:30', 40],
  ])
  const high = planDay(day, DEFAULT_SLOTS, () => 0.999)
  assert.deepEqual(high.map((p) => [p.name, hhmm(p.start)]), [['早上', '08:30'], ['中午', '12:30'], ['傍晚', '18:30'], ['晚上', '22:30']])
  const some = planDay(day, [{ name: '有时', from: '20:00', to: '20:00', minutes: 30, chance: 0.5 }], () => 0.9)
  assert.deepEqual(some, []) // 0.9 >= chance 0.5: not that day
  assert.equal(hhmm(planBed(day, DEFAULT_SLEEP, () => 0)), '23:30')
  assert.equal(hhmm(planBed(day, DEFAULT_SLEEP, () => 0.999)), '23:59')
  const fixed = planDay(day, [{ name: '固定', from: '10:00', to: '10:00', minutes: 30 }], () => 0.7)
  assert.equal(hhmm(fixed[0].start), '10:00')
})

test('findSlot: running now, next, or none', () => {
  const plans = [
    { name: '早上', start: at(7, 50), minutes: 40 },
    { name: '中午', start: at(12, 0), minutes: 40 },
  ]
  assert.deepEqual(findSlot(at(7, 0), plans), { plan: plans[0], until: at(8, 30), active: false })
  assert.equal(findSlot(at(8, 0), plans).active, true)
  assert.equal(findSlot(at(8, 0), plans).until, at(8, 30))
  // only 2 minutes left of breakfast: wait for lunch instead
  assert.equal(findSlot(at(8, 28), plans).plan.name, '中午')
  assert.equal(findSlot(at(13, 0), plans), undefined)
})

test('formatDuration', () => {
  assert.equal(formatDuration(30_000), '不到一分钟')
  assert.equal(formatDuration(200 * 60_000), '3小时20分钟')
  assert.equal(formatDuration(26 * 3600_000), '1天2小时')
})

test('localIso', () => {
  assert.equal(localIso(new Date(2026, 0, 2, 3, 4, 5)), '2026-01-02T03:04:05')
})

test('buildWakeMessage', () => {
  const first = buildWakeMessage({ slotName: '早上', start: at(7, 52), until: at(8, 32), news: [], look: 'LOOK' })
  assert.match(first, /^（自由活动时间到了：早上，07:52–08:32，共 40 分钟。）/)
  assert.doesNotMatch(first, /这段时间里|在这之前/)
  assert.match(first, /先用 diary_write 写下这次的日记，再调用 end_free_time/)
  const morning = buildWakeMessage({ slotName: '早上', start: at(7, 52), until: at(8, 32), before: '在床上睡觉', news: [], look: 'LOOK', wokeUp: true })
  assert.match(morning, /^（07:52，你醒了。早上的自由活动开始了：到 08:32，共 40 分钟。）/)
  assert.doesNotMatch(morning, /在床上睡觉/)
  assert.match(first, /日常事务/)
  const later = buildWakeMessage({
    slotName: '中午', start: at(12, 0), until: at(12, 40), before: '窝在沙发上看书',
    news: ['邮箱里来了包裹', '邮箱里来了包裹', '菜地1里的萝卜成熟了'], lastNote: '捡了贝壳。', look: 'LOOK',
  })
  assert.match(later, /在这之前，你一直在过平淡的日常——刚才在窝在沙发上看书。/)
  assert.match(later, /日记里最近的一段：捡了贝壳。/)
  assert.match(later, /这段时间里：邮箱里来了包裹；菜地1里的萝卜成熟了。/)
  const resumed = buildWakeMessage({ slotName: '傍晚', start: at(18, 0), until: at(18, 20), news: [], look: 'L', resumed: true })
  assert.match(resumed, /继续.*还有 20 分钟/)
})

test('buildNudge', () => {
  const n = buildNudge({ left: 12, look: 'LOOK' })
  assert.match(n, /还剩 12 分钟/)
  assert.match(n, /diary_write.*end_free_time/)
})

test('recapEvents skips moves and duplicates', () => {
  const events = [
    { kind: 'move', text: '走到了庭院' }, { kind: 'care', text: '给绿萝浇了水' },
    { kind: 'care', text: '给绿萝浇了水' }, { kind: 'cook', text: '做了煎蛋' },
  ]
  assert.deepEqual(recapEvents(events), ['给绿萝浇了水', '做了煎蛋'])
  const many = Array.from({ length: 15 }, (_, i) => ({ kind: 'x', text: `事${i}` }))
  const r = recapEvents(many, 5)
  assert.equal(r.length, 5)
  assert.match(r[4], /等 11 件事/)
  const long = recapEvents([{ kind: 'mail', text: '读了一封信：' + '很长'.repeat(50) }])
  assert.ok(long[0].length <= 42 && long[0].endsWith('……'))
  const msg = buildWakeMessage({ slotName: '早上', start: at(8, 0), until: at(8, 40), recap: ['喂了团子'], news: [], look: 'L' })
  assert.match(msg, /上次自由活动的时候，你喂了团子。/)
})
