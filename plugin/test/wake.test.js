import { test } from 'node:test'
import assert from 'node:assert/strict'

import { formatDuration, inQuietHours, msUntilQuietEnds, parseQuietHours, randomDelayMs } from '../lib/wake.js'

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
