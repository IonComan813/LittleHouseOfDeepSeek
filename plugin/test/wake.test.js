import { test } from 'node:test'
import assert from 'node:assert/strict'

import { buildWakeMessage, recapEvents, formatDuration, inQuietHours, localIso, msUntilQuietEnds, parseQuietHours, randomDelayMs } from '../lib/wake.js'

const at = (h, m) => new Date(2026, 10, 13, h, m, 0, 0)

test('parseQuietHours', () => {
  assert.deepEqual(parseQuietHours('23:30-07:00'), { start: 1410, end: 420 })
  assert.equal(parseQuietHours(''), undefined)
  assert.throws(() => parseQuietHours('23-7'))
  assert.throws(() => parseQuietHours('25:00-07:00'))
})

test('quiet window wrapping midnight', () => {
  const q = parseQuietHours('23:30-07:00')
  assert.equal(inQuietHours(at(23, 45), q), true)
  assert.equal(inQuietHours(at(3, 0), q), true)
  assert.equal(inQuietHours(at(7, 0), q), false)
  assert.equal(inQuietHours(at(12, 0), q), false)
  assert.equal(msUntilQuietEnds(at(6, 30), q), 30 * 60_000)
  assert.equal(msUntilQuietEnds(at(12, 0), q), 0)
})

test('quiet window within a day', () => {
  const q = parseQuietHours('13:00-14:00')
  assert.equal(inQuietHours(at(13, 30), q), true)
  assert.equal(inQuietHours(at(14, 0), q), false)
})

test('randomDelayMs stays in range', () => {
  assert.equal(randomDelayMs(10, 20, () => 0), 10 * 60_000)
  assert.equal(randomDelayMs(10, 20, () => 1), 20 * 60_000)
  assert.equal(randomDelayMs(20, 10, () => 0.5), 15 * 60_000)
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
  const first = buildWakeMessage({ news: [], look: 'LOOK', maxActions: 12 })
  assert.match(first, /^（你醒了过来。）/)
  assert.doesNotMatch(first, /不在的时候|上次的小记/)
  const later = buildWakeMessage({
    sinceText: '3小时', news: ['邮箱里来了包裹', '邮箱里来了包裹', '菜地1里的萝卜成熟了'],
    lastNote: '捡了贝壳。', look: 'LOOK', maxActions: 6,
  })
  assert.match(later, /距离上次活动过了3小时/)
  assert.match(later, /日记里最近的一段：捡了贝壳。/)
  assert.match(later, /你不在的时候：邮箱里来了包裹；菜地1里的萝卜成熟了。/)
  assert.match(later, /最多 6 次/)
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
  const msg = buildWakeMessage({ recap: ['喂了团子'], news: [], look: 'L', maxActions: 3 })
  assert.match(msg, /上次醒着的时候，你喂了团子。/)
})
