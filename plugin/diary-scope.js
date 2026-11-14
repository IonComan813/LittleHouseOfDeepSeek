// dsh-little-house/diary — the resident's diary tools, mountable in any preset.
//
// Mounted in the life preset with `source: 小屋`; the QQ preset (M5) mounts the
// same row with `source: QQ`, so every part of her life writes to one diary.
// In the life preset she writes one entry before every end_free_time (her
// memory is built from the diary); what to write is up to her.

import Schema from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { join } from 'node:path'

import { MAX_ENTRY_CHARS, appendEntry, listDays, readDay, resolveDay } from './lib/diary.js'

export const name = 'little-house-diary'
export const inject = ['tools', 'littleHouse']

export const DIARY_TOOLS = ['diary_write', 'diary_read']

export const Config = Schema.object({
  source: Schema.string().default('小屋').description('写进日记时标注的来源，如 小屋、QQ'),
})

export function apply(ctx, config) {
  const dir = () => join(ctx.littleHouse.stateDir, 'diary')
  const textOutput = {
    schema: { type: 'string' },
    render: (_args, value) => [{ type: 'text', text: value }],
  }

  ctx.tools.register(defineTool({
    name: 'diary_write',
    description: `在今天的日记里写一段（长期保存；以后你记得的事主要来自日记）。写你觉得重要的、想记住的：值得记住的事和新发现、心情和想法、想做的事和打算。不用记流水账。一段最多 ${MAX_ENTRY_CHARS} 字。`,
    parameters: {
      entry: { type: 'string', required: true, description: '要写进日记的内容，第一人称' },
    },
    output: textOutput,
    async execute(args, exec) {
      const slot = ctx.littleHouse.markDiary(exec?.agent?.id)
      const source = slot ? `${config.source} · ${slot}` : config.source
      const now = new Date()
      const { day, time } = await appendEntry(dir(), now, source, args.entry, ctx.littleHouse.dayKey(now))
      const offer = slot ? await ctx.littleHouse.shareOffer(exec?.agent?.id) : ''
      return `（已写进 ${day} 的日记，${time}。）${offer}`
    },
  }))

  ctx.tools.register(defineTool({
    name: 'diary_read',
    description: '翻看某一天的日记。day 可以写「今天」「昨天」「前天」或 YYYY-MM-DD；不写就是今天。',
    parameters: {
      day: { type: 'string', description: '哪一天' },
    },
    output: textOutput,
    async execute(args) {
      const day = resolveDay(args.day, new Date())
      const recent = (await listDays(dir())).slice(0, 10)
      const hint = recent.length ? `最近有日记的日子：${recent.join('、')}` : '你还没有写过日记。'
      if (!day) return `看不懂「${args.day}」是哪天。${hint}`
      return (await readDay(dir(), day)) ?? `${day} 没有日记。${hint}`
    },
  }))
}
