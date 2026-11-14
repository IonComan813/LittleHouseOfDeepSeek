// dsh-little-house/memory — mounted inside the `little-house-memory` agent
// preset: the once-a-day session that turns a day's diary and QQ chats into
// her memory (see index.js summariseDay and lib/memory.js).
//
// No persona (it is not her talking: it keeps the summary plain and the
// context small) and no tools at all.

export const name = 'little-house-memory-scope'
export const inject = ['tools', 'systemPrompt']

const RULES = `你是记忆整理员。你会读到一个人一天的日记和聊天记录，以及她现有的记忆，然后按要求输出一个 JSON 对象。
- 只根据给你的内容整理，不编造，不评价。
- 用她自己的口吻（第一人称）写，简洁具体：时间、东西、人名写清楚。
- 只输出 JSON，不要任何别的文字。`

export function apply(ctx) {
  const all = ctx.tools.definitions().map((d) => d.name)
  if (all.length > 0) ctx.tools.restrict({ deny: all })
  ctx.tools.guard((exec) => `这里不能用工具（${exec.name}）。`)
  ctx.systemPrompt.suppressRuntimeContext()
  ctx.systemPrompt.section({ name: 'little-house:memory', order: 0, complete: true, interpolate: false, text: RULES })
}
