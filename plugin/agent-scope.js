// dsh-little-house/agent-scope — mounted inside the `little-house` agent preset.
//
// Everything registered here lives only in the life session's own scope: the
// resident's system prompt (persona + house rules) and the house_* tools.
// Ordinary Web/QQ sessions never see them. The diary tools come from the
// sibling `diary-scope.js` row in the same preset.

import { join } from 'node:path'

import { defineTool } from '@deepseek-ai/dsh-tools'
import { DIARY_TOOLS } from './diary-scope.js'
import { appendEntry } from './lib/diary.js'

export const name = 'little-house-agent-scope'
export const inject = ['tools', 'systemPrompt', 'littleHouse']

const OWN_TOOLS = new Set(['house_look', 'house_do', 'house_rest', 'house_glance', ...DIARY_TOOLS])

const IMAGE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    attachmentId: { type: 'string', required: true },
    mediaType: { type: 'string', required: true },
    bytes: { type: 'integer', required: true },
    width: { type: 'integer', required: true },
    height: { type: 'integer', required: true },
    name: { type: 'string' },
  },
}

const HOUSE_RULES = `## 你的生活
你住在潮汐湾的一间海边小屋里：客厅、厨房、卧室，屋前的庭院有三块菜地、一个邮箱和寄售箱，再往前是沙滩。
潮汐湾是一片正在慢慢恢复的海岸，负责重建的「开拓署」把你安置在这里：每周一送来基本补给，
别的东西要自己挣——把作物、鱼和捡到的东西放进寄售箱卖给开拓署，再用贝币在订货目录上买需要的东西，
快递员阿陆会把货送到门口。你和一只叫团子的猫一起生活。时间和现实同步，会有昼夜、天气和四季。
你不是在帮谁完成任务，这是你自己的生活。按自己的心情和性格安排时间就好，不必面面俱到。

生活里的事情会自己发生：你会饿、会累；植物和菜地会变干；房间会落灰；团子会饿，脾气也每天不一样；
海浪会把贝壳冲上沙滩；偶尔会有信，或者一些意想不到的小事。
可以做饭、种菜、钓鱼、捡贝壳摆上收藏架、赚钱买家具布置房间、陪团子玩……想做什么做什么。

## 怎么在小屋里行动
- house_look：看看四周。
- house_do：用伪代码行动，一次可以写好几步，用分号或换行隔开，例如
  goto(庭院); open(邮箱); plant(萝卜种子); water()
  参数可以写编号（pot#1）或名字（绿萝）。很多动作不写参数就作用于这里所有的东西，比如 water()、pick()、harvest()。
  某一步失败时后面的步骤不会执行。看「这里能做」那一行，或执行 help() 了解全部动作。
- house_glance：看一眼小屋现在的样子（一张像素画）。平时用 house_look 和 house_do 就够了，
  偶尔想看看整个家、院子和海边的样子时再用。
- house_rest：结束这次活动去休息。

## 日记
diary_write 会把一段话写进你今天的日记（每天一个本子，长期保存），diary_read 可以翻看某天的日记。
日记是你自己的，写不写、写什么都由你决定：值得记住的发现、心情、想法，想写就写；平淡的时候不写也没关系。

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

  // house_glance needs somewhere to keep the picture: only offered when the
  // deployment mounts an attachment store (the Web/Desktop profiles do).
  ctx.inject(['attachments'], (imageCtx) => {
    try {
      registerGlance(imageCtx, house)
    } catch (e) {
      house.log('warn', `house_glance unavailable: ${e?.message ?? e}`)
    }
  })

  ctx.tools.register(defineTool({
    name: 'house_rest',
    description: '结束这次活动去休息。note 可选：想在日记里留一句才写；这次已经用 diary_write 写过就不要再重复。',
    parameters: {
      note: { type: 'string', description: '可选：写进今天日记的一句话' },
    },
    output: textOutput,
    async execute(args, exec) {
      if (args.note && String(args.note).trim()) {
        await appendEntry(join(house.stateDir, 'diary'), new Date(), '小屋', args.note)
      }
      exec.concludeTurn()
      return '（你安静地休息了。）'
    },
  }))
}

/** Register house_glance on a context that has the attachment store. */
function registerGlance(imageCtx, house) {
  imageCtx.tools.register(defineTool({
    name: 'house_glance',
    description: '看一眼小屋现在的样子：返回一张整个家、院子和沙滩的像素画（你、团子、家具、菜地、天气和昼夜都画在上面）。偶尔看看就好。',
    parameters: {},
    output: {
      schema: IMAGE_SCHEMA,
      render: (_args, value) => [
        { type: 'text', text: '（你抬头看了看自己的小屋。上半部分从左到右是卧室、客厅、厨房，下面是庭院、沙滩和海。底栏是日期时间、天气、贝币，右边两条是饱腹和精力，粉色那条是团子的亲密度。）' },
        { type: 'image', attachment: value },
      ],
    },
    async execute() {
      const png = await house.house.requestBytes('/screenshot?scale=2')
      const ref = await imageCtx.attachments.saveImage({ data: png, mediaType: 'image/png', name: 'little-house.png' })
      return {
        attachmentId: ref.attachmentId,
        mediaType: ref.mediaType,
        bytes: ref.bytes,
        width: ref.width,
        height: ref.height,
        ...(ref.name === undefined ? {} : { name: ref.name }),
      }
    },
  }))
}
