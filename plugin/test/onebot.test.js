import assert from 'node:assert/strict'
import test from 'node:test'

import { SILENCE, cqToSegments, formatLine, inHours, qqDay, readMessage, splitReply, toSegments } from '../lib/onebot.js'

test('readMessage: text, faces, pictures, mentions', () => {
  const m = readMessage([
    { type: 'at', data: { qq: '10001' } },
    { type: 'text', data: { text: ' 你看' } },
    { type: 'face', data: { id: '14' } },
    { type: 'image', data: { url: 'https://x/a.jpg', file: 'a.jpg' } },
    { type: 'at', data: { qq: '20002', name: '阿陆' } },
    { type: 'reply', data: { id: '77' } },
  ], '10001')
  assert.equal(m.text, '你看[表情:微笑][图片]@阿陆')
  assert.deepEqual(m.images, ['https://x/a.jpg'])
  assert.equal(m.mentioned, true)
  assert.equal(m.replyTo, '77')
  assert.equal(readMessage([{ type: 'at', data: { qq: '20002' } }], '10001').mentioned, false)
  assert.equal(readMessage([{ type: 'mface', data: { url: 'https://x/s.gif', summary: '[开心]' } }]).text, '[表情包]')
})

test('CQ strings still work', () => {
  const segs = cqToSegments('早[CQ:face,id=14]呀&#91;不是表情&#93;')
  assert.deepEqual(segs.map((s) => s.type), ['text', 'face', 'text'])
  assert.equal(readMessage('早[CQ:face,id=14]呀').text, '早[表情:微笑]呀')
})

test('toSegments turns [表情:名称] into QQ faces', () => {
  assert.deepEqual(toSegments('好呀[表情:微笑]！'), [
    { type: 'text', data: { text: '好呀' } },
    { type: 'face', data: { id: '14' } },
    { type: 'text', data: { text: '！' } },
  ])
  assert.deepEqual(toSegments('[表情:不存在的表情]'), [{ type: 'text', data: { text: '[表情:不存在的表情]' } }])
})

test('splitReply: bubbles, silence, no Markdown', () => {
  assert.deepEqual(splitReply('第一条\n\n**第二条**\n\n三\n\n四'), ['第一条', '第二条', '三\n四'])
  assert.deepEqual(splitReply(SILENCE), [])
  assert.deepEqual(splitReply('  '), [])
})

test('qqDay changes at the rollover hour', () => {
  assert.equal(qqDay(new Date(2026, 10, 15, 2, 30), 4), '2026-11-14')
  assert.equal(qqDay(new Date(2026, 10, 15, 4, 0), 4), '2026-11-15')
})

test('inHours wraps midnight', () => {
  assert.equal(inHours(new Date(2026, 0, 1, 3, 0), '00:00', '08:00'), true)
  assert.equal(inHours(new Date(2026, 0, 1, 9, 0), '00:00', '08:00'), false)
  assert.equal(inHours(new Date(2026, 0, 1, 23, 30), '23:00', '07:00'), true)
})

test('formatLine', () => {
  assert.equal(formatLine({ name: '主人', text: '在吗' }), '主人：在吗')
  assert.equal(formatLine({ group: '潮汐湾', name: '阿陆', text: '在吗' }), '[潮汐湾] 阿陆：在吗')
  assert.equal(formatLine({ group: '潮汐湾', name: '老板', isOwner: true, text: '在吗' }), '[潮汐湾] 老板（主人）：在吗')
})

test('voice, video and files are stopped, not passed on', () => {
  const m = readMessage([{ type: 'record', data: { file: 'a.amr' } }, { type: 'file', data: { name: 'x.pdf' } }])
  assert.equal(m.text, '')
  assert.deepEqual(m.images, [])
  assert.deepEqual(m.dropped, ['record', 'file'])
  assert.equal(readMessage([{ type: 'text', data: { text: '听' } }, { type: 'record', data: {} }]).text, '听')
})
