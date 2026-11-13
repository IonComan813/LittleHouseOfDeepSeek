// dsh-little-house/diary — the resident's diary tools, mountable in any preset.
//
// Mounted in the life preset with `source: 小屋`; the QQ preset (M5) mounts the
// same row with `source: QQ`, so every part of her life writes to one diary.
// Whether to write, and what, is the model's own decision.

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
    description: `在今天的日记里写一段（会长期保存，以后可以翻看）。日记是你自己的：想记的时候才记——感受、发现、想法、想记住的人和事；不想记就不记，也不用记流水账。一段最多 ${MAX_ENTRY_CHARS} 字。`,
    parameters: {
      entry: { type: 'string', required: true, description: '要写进日记的内容，第一人称' },
    },
    output: textOutput,
    async execute(args) {
      const { day, time } = await appendEntry(dir(), new Date(), config.source, args.entry)
      return `（已写进 ${day} 的日记，${time}。）`
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
