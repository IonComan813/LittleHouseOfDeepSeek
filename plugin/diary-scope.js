// dsh-little-house/diary — the resident's diary tools, mountable in any preset.
//
// Mounted in the life preset with `source: 小屋`; the QQ preset (M5) mounts the
// same row with `source: QQ`, so every part of her life writes to one diary.
// She may write, change and delete today's entries whenever she is awake (free
// time, answering the phone, before bed); one entry is required before every
// end_free_time. Her memory is built from the diary every night.


import Schema from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { join } from 'node:path'

import { MAX_ENTRY_CHARS, appendEntry, editEntry, listDays, readDay, resolveDay } from './lib/diary.js'

export const name = 'little-house-diary'
export const inject = ['tools', 'littleHouse']

export const DIARY_TOOLS = ['diary_write', 'diary_edit', 'diary_read']

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
    description: `在今天的日记里写一段（长期保存；以后你记得的事主要来自日记）。醒着的时候随时都可以写。写你觉得重要的、想记住的：值得记住的事和新发现、心情和想法、想做的事和打算。不用记流水账。一段最多 ${MAX_ENTRY_CHARS} 字。`,
    parameters: {
      entry: { type: 'string', required: true, description: '要写进日记的内容，第一人称' },
    },
    output: textOutput,
    async execute(args, exec) {
      const slot = ctx.littleHouse.markDiary(exec?.agent?.id)
      const source = slot ? `${config.source} · ${slot}` : config.source
      const now = new Date()
      const { day, time } = await appendEntry(dir(), now, source, args.entry, ctx.littleHouse.dayKey(now))
      return `（已写进 ${day} 的日记，${time}。）`
    },
  }))

  ctx.tools.register(defineTool({
    name: 'diary_edit',
    description: '修改或删掉今天日记里的某一段：time 是那一段的时间（如 08:35，diary_read 看得到），text 是改好的整段内容；text 写空字符串就是删掉这一段。只能改今天的。',
    parameters: {
      time: { type: 'string', required: true, description: '要改的那一段的时间，HH:MM' },
      text: { type: 'string', required: true, description: '改好的整段内容（空 = 删掉）' },
    },
    output: textOutput,
    async execute(args) {
      const day = ctx.littleHouse.dayKey(new Date())
      const r = await editEntry(dir(), day, args.time, args.text)
      if (!r.ok) return r.times.length ? `今天的日记里没有 ${args.time} 那一段。有的是：${r.times.join('、')}。` : '今天还没有日记。'
      return String(args.text ?? '').trim() ? `（改好了 ${args.time} 那一段。）` : `（删掉了 ${args.time} 那一段。）`
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
      const day = resolveDay(args.day, new Date(ctx.littleHouse.dayKey(new Date()) + 'T12:00'))
      const recent = (await listDays(dir())).slice(0, 10)
      const hint = recent.length ? `最近有日记的日子：${recent.join('、')}` : '你还没有写过日记。'
      if (!day) return `看不懂「${args.day}」是哪天。${hint}`
      return (await readDay(dir(), day)) ?? `${day} 没有日记。${hint}`
    },
  }))
}
