import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { appendEntry, lastEntry, lastEntryNote, listDays, previousDiary, readDay, resolveDay } from '../lib/diary.js'

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

test('previousDiary: the newest day before today, whole, or its end when long', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'diary-prev-'))
  assert.equal(await previousDiary(dir, '2026-11-15'), undefined)
  await appendEntry(dir, new Date('2026-11-12T09:00'), '小屋', '种了萝卜。', '2026-11-12')
  await appendEntry(dir, new Date('2026-11-15T08:00'), '小屋', '今天的。', '2026-11-15')
  let prev = await previousDiary(dir, '2026-11-15')
  assert.equal(prev.day, '2026-11-12') // no diary on the 13th and 14th: the last one there is
  assert.match(prev.text, /种了萝卜/)
  assert.doesNotMatch(prev.text, /今天的/)
  await appendEntry(dir, new Date('2026-11-14T21:00'), '小屋', '明天想去钓鱼。'.repeat(50), '2026-11-14')
  await appendEntry(dir, new Date('2026-11-14T23:40'), '小屋', '睡前：答应阿青明天拍海的照片。', '2026-11-14')
  prev = await previousDiary(dir, '2026-11-15', 200)
  assert.equal(prev.day, '2026-11-14')
  assert.ok(prev.cut)
  assert.ok(prev.text.length <= 200)
  assert.match(prev.text, /答应阿青/) // the end is kept
})
