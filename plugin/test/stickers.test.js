import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { listStickers, splitStickers } from '../lib/stickers.js'

test('the built-in stickers are there, and the owner\'s own win', async () => {
  const builtin = fileURLToPath(new URL('../stickers/', import.meta.url))
  const own = await mkdtemp(join(tmpdir(), 'stickers-'))
  await writeFile(join(own, '震惊.png'), 'x')
  await writeFile(join(own, '新的.gif'), 'x')
  await writeFile(join(own, 'notes.txt'), 'x')
  const all = await listStickers([builtin, own, join(own, 'missing')])
  assert.ok(all.size >= 27)
  assert.ok(all.has('点赞') && all.has('在吗？') && all.has('（气鼓鼓）去问你的豆包'))
  assert.equal(all.get('震惊'), join(own, '震惊.png'))
  assert.ok(all.has('新的'))
  assert.ok(!all.has('notes'))
})

test('splitStickers keeps the order and lists names that are not stickers', () => {
  const names = new Map([['点赞', 'a'], ['收到（敬礼）', 'b']])
  assert.deepEqual(splitStickers('好呀 [表情包:点赞] 马上去[表情包：收到（敬礼）]', names), {
    parts: [{ text: '好呀' }, { sticker: '点赞' }, { text: '马上去' }, { sticker: '收到（敬礼）' }], unknown: [],
  })
  assert.deepEqual(splitStickers('[表情包:点个赞]', names).unknown, ['点个赞'])
  assert.deepEqual(splitStickers('没有表情包', names), { parts: [{ text: '没有表情包' }], unknown: [] })
})
