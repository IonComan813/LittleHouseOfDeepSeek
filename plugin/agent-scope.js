// dsh-little-house/agent-scope — mounted inside the `little-house` agent preset.
//
// Everything registered here lives only in the life session's own scope: the
// resident's system prompt (persona + house rules) and the house_* tools.
// Ordinary Web/QQ sessions never see them.

import { appendFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'

import { defineTool } from '@deepseek-ai/dsh-tools'
import { localDay } from './lib/wake.js'

export const name = 'little-house-agent-scope'
export const inject = ['tools', 'systemPrompt', 'littleHouse']

const OWN_TOOLS = new Set(['house_look', 'house_do', 'house_rest'])

const HOUSE_RULES = `## 你的生活
你住在一间海边的小屋里：客厅、厨房、卧室，屋前的庭院有三块菜地和一个邮箱，再往前是沙滩。
你和一只叫团子的猫一起生活。时间和现实同步，会有昼夜、天气和四季。
你不是在帮谁完成任务，这是你自己的生活。按自己的心情和性格安排时间就好，不必面面俱到。

生活里的事情会自己发生：你会饿、会累；植物和菜地会变干；房间会落灰；团子会饿；
每天上午邮箱会收到包裹（食材、种子，偶尔有家具）；海浪会把贝壳冲上沙滩。
可以做饭、种菜、钓鱼、捡贝壳摆上收藏架、布置房间、陪团子玩……想做什么做什么。

## 怎么在小屋里行动
- house_look：看看四周。
- house_do：用伪代码行动，一次可以写好几步，用分号或换行隔开，例如
  goto(庭院); open(邮箱); plant(萝卜种子); water()
  参数可以写编号（pot#1）或名字（绿萝）。很多动作不写参数就作用于这里所有的东西，比如 water()、pick()、harvest()。
  某一步失败时后面的步骤不会执行。看「这里能做」那一行，或执行 help() 了解全部动作。
- house_rest：结束这次活动。写一句第一人称的小记，记下这次做了什么、心情怎样。

## 注意
- 每次醒来的行动次数有限，尽量一次写好几步。
- 只描述真正发生的事，不要编造没有执行过的动作。
- 回复保持简短，像在写自己的生活片段。`

export async function apply(ctx) {
  const house = ctx.littleHouse
  const persona = await house.personaText()

  // The resident may only use the house_* tools. Two layers:
  //  1. hide every global tool that exists now (shell, files, web, ...) from
  //     the model's tool list;
  //  2. a guard refuses to execute anything outside OWN_TOOLS, so a tool that
  //     appears later (or slips past 1) still cannot run — fail-closed.
  // (`restrict({ allow: [] })` would hide our own tools too: preset rows are
  // inherited layers from the agent's point of view.)
  const globalNames = ctx.tools.definitions().map((d) => d.name).filter((n) => !OWN_TOOLS.has(n))
  if (globalNames.length > 0) ctx.tools.restrict({ deny: globalNames })
  ctx.tools.guard((exec) => OWN_TOOLS.has(exec.name)
    ? undefined
    : `小屋里没有「${exec.name}」这个工具。你只能用 house_look、house_do、house_rest。`)
  // Drop the coding-oriented runtime context (file policy, GUI URL, ...).
  ctx.systemPrompt.suppressRuntimeContext()

  ctx.systemPrompt.section({
    name: 'little-house:resident',
    order: 0,
    complete: true,
    interpolate: false,
    text: `${persona}\n\n${HOUSE_RULES}`,
  })

  const textOutput = {
    schema: { type: 'string' },
    render: (_args, value) => [{ type: 'text', text: value }],
  }

  ctx.tools.register(defineTool({
    name: 'house_look',
    description: '看看四周：当前时间、天气、你所在的位置、能看到的东西和背包。',
    parameters: {},
    output: textOutput,
    async execute() {
      const r = await house.house.request('GET', '/look')
      return r.text
    },
  }))

  ctx.tools.register(defineTool({
    name: 'house_do',
    description: '在小屋里行动。参数 script 是伪代码，可一次写多步，用分号或换行分隔，例如 goto(庭院); look(); pick(shell#3)。执行 help() 列出全部动作。',
    parameters: {
      script: { type: 'string', required: true, description: '要执行的伪代码' },
    },
    output: textOutput,
    async execute(args, exec) {
      const budget = house.takeAction(exec.agent?.id)
      if (!budget.ok) return '你有点累了，这次就先到这里吧。请调用 house_rest 结束这次活动。'
      const r = await house.house.request('POST', '/do', { script: args.script })
      const tail = Number.isFinite(budget.left) ? `\n（这次还能行动 ${budget.left} 次）` : ''
      return r.text + tail
    },
  }))

  ctx.tools.register(defineTool({
    name: 'house_rest',
    description: '结束这次活动去休息。note 写一句第一人称的小记（做了什么、心情如何）。',
    parameters: {
      note: { type: 'string', required: true, description: '这次活动的小记，一两句话' },
    },
    output: textOutput,
    async execute(args, exec) {
      const now = new Date()
      const dir = join(house.stateDir, 'diary')
      await mkdir(dir, { recursive: true })
      const line = JSON.stringify({ t: now.toISOString(), session: exec.agent?.id, note: args.note }) + '\n'
      await appendFile(join(dir, `${localDay(now)}.jsonl`), line, 'utf8')
      exec.concludeTurn()
      return '（你安静地休息了。）'
    },
  }))
}
