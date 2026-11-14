import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { appendEntry, lastEntry, lastEntryNote, listDays, readDay, resolveDay } from '../lib/diary.js'

test('diary entries accumulate in one file per day', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'lh-diary-'))
  try {
    await appendEntry(dir, new Date(2026, 10, 13, 9, 5), '小屋', '早上给绿萝浇了水。')
    await appendEntry(dir, new Date(2026, 10, 13, 21, 30), 'QQ', '和主人聊了会儿天。')
    await appendEntry(dir, new Date(2026, 10, 14, 8, 0), '小屋', '团子今天很黏人。')
    const text = await readFile(join(dir, '2026-11-13.md'), 'utf8')
    assert.match(text, /^# 2026-11-13 周五\n/)
    assert.equal(text.match(/^# /gm).length, 1)
    assert.match(text, /### 09:05 · 小屋\n\n早上给绿萝浇了水。/)
    assert.match(text, /### 21:30 · QQ\n\n和主人聊了会儿天。/)
    assert.deepEqual(await listDays(dir), ['2026-11-14', '2026-11-13'])
    assert.equal(await lastEntry(dir), '团子今天很黏人。')
    assert.equal(await readDay(dir, '2026-01-01'), undefined)
    await assert.rejects(appendEntry(dir, new Date(), '小屋', '   '))
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})

test('resolveDay', () => {
  const now = new Date(2026, 10, 13, 12)
  assert.equal(resolveDay('', now), '2026-11-13')
  assert.equal(resolveDay('昨天', now), '2026-11-12')
  assert.equal(resolveDay('yesterday', now), '2026-11-12')
  assert.equal(resolveDay('2026-10-01', now), '2026-10-01')
  assert.equal(resolveDay('上周', now), undefined)
})

test('lastEntryNote says when the entry was written', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'diary-'))
  await appendEntry(dir, new Date(2026, 10, 14, 10, 5), '小屋 · 早上', '上午去了沙滩。')
  assert.equal(await lastEntryNote(dir, new Date(2026, 10, 14, 12, 0)), '（今天 10:05 写的）上午去了沙滩。')
  assert.equal(await lastEntryNote(dir, new Date(2026, 10, 15, 8, 0)), '（昨天 10:05 写的）上午去了沙滩。')
})

test('editEntry changes or deletes one entry by its time', async () => {
  const { editEntry } = await import('../lib/diary.js')
  const dir = await mkdtemp(join(tmpdir(), 'diary-'))
  await appendEntry(dir, new Date(2026, 10, 14, 8, 5), '小屋 · 早上', '早上浇了水。')
  await appendEntry(dir, new Date(2026, 10, 14, 12, 30), '小屋 · 中午', '中午做了饭。')
  let r = await editEntry(dir, '2026-11-14', '08:05', '早上浇了水，绿萝长了新叶。')
  assert.equal(r.ok, true)
  let text = await readDay(dir, '2026-11-14')
  assert.match(text, /### 08:05 · 小屋 · 早上\n\n早上浇了水，绿萝长了新叶。\n\n### 12:30/)
  r = await editEntry(dir, '2026-11-14', '12:30', '')
  assert.deepEqual(r.times, ['08:05'])
  text = await readDay(dir, '2026-11-14')
  assert.doesNotMatch(text, /12:30|中午做了饭/)
  assert.equal((await editEntry(dir, '2026-11-14', '09:00', 'x')).ok, false)
})
