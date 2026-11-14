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
import { OVER_TEXT, REST_TEXT } from './lib/wake.js'

export const name = 'little-house-agent-scope'
export const inject = ['tools', 'systemPrompt', 'littleHouse']

const OWN_TOOLS = new Set(['house_surroundings', 'house_do', 'end_free_time', 'house_render', ...DIARY_TOOLS])

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

## 自由活动时间
每天有几段自由活动时间（早上、中午、傍晚，有时还有深夜），每段四十分钟左右，开始时会告诉你。
这段时间由你自己安排。其余时间你的角色会自己过平淡的日常（看书、发呆、晒太阳、睡觉、随便吃点东西），不需要你操心。

生活里的事情会自己发生：你会饿、会累；植物和菜地会变干；房间会落灰；团子会饿，脾气也每天不一样；
海浪会把贝壳冲上沙滩；偶尔会有信，或者一些意想不到的小事。
可以做饭、种菜、钓鱼、捡贝壳摆上收藏架、赚钱买家具布置房间、陪团子玩……想做什么做什么。

## 怎么在小屋里行动
- house_surroundings：看看四周。
- house_do：用伪代码行动，一次可以写好几步，用分号或换行隔开，例如
  goto(庭院); open(邮箱); plant(萝卜种子); water()
  参数可以写编号（pot#1）或名字（绿萝）。很多动作不写参数就作用于这里所有的东西，比如 water()、pick()、harvest()。
  某一步失败时后面的步骤不会执行。house_surroundings 里「这里能做」一行列出了在这里能用的动作。
  不确定括号里写什么时，只写动作名就行（例如 cook、plant、sell、order），会列出现在能填的东西：能做的菜、背包里的种子、能卖的东西……
- 做事要花真实的时间：走路按路程（相邻房间十来秒），浇水、捡东西几秒到几十秒，打扫一个房间最多四分钟，钓一竿一到三分钟，吃一顿饭两分钟。
  house_do 会等到这一串都做完才返回，结果里有每一步的时间和自由活动还剩多久。
- 做饭：炒、煎要一直守在灶台边（约两分钟，中途走开会糊）；炖、煮、烤、蒸先忙一分半钟，下锅后自己熟（约三分钟），
  这期间可以去做别的，好了以后回厨房就会盛出来；也可以 wait() 等着。灶台有两个灶眼。recipes() 里写着每道菜的做法。
- 打扫可以分几次：clean(2) 只扫两分钟，没扫完的下次接着扫。
- house_render：看一眼小屋现在的样子（一张静态像素画，只在你看的那一刻画一帧）。
  画画要用到这台机器的算力，而这台机器不算宽裕：平时用 house_surroundings 和 house_do 就够了，
  只在真想看看整个家、院子和海边的样子时偶尔看一眼，一次自由活动最多一两次。
- end_free_time：结束这次自由活动。

## 日记
diary_write 会把一段话写进你今天的日记（每天一个本子，长期保存），diary_read 可以翻看某天的日记。
日记是你自己的，写不写、写什么都由你决定：值得记住的发现、心情、想法，想写就写；平淡的时候不写也没关系。

## 注意
- 时间是有限的：一圈想做的事大概二十分钟就够了，不必把时间填满，做完想做的就 end_free_time。
- 尽量一次写好几步，少来回问。
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
    : `小屋里没有「${exec.name}」这个工具。你只能用 house_surroundings、house_do、house_render、end_free_time 和日记工具。`)
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
    name: 'house_surroundings',
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
    description: '在小屋里行动。参数 script 是伪代码，可一次写多步，用分号或换行分隔，例如 goto(庭院); look(); pick(shell#3)。动作会花真实的时间，做完才返回。执行 help() 列出全部动作。',
    parameters: {
      script: { type: 'string', required: true, description: '要执行的伪代码' },
    },
    output: textOutput,
    timeoutMs: 60 * 60_000,
    async execute(args, exec) {
      const sessionId = exec.agent?.id
      if (house.windowOver(sessionId)) return OVER_TEXT
      const budget = house.takeAction(sessionId)
      if (!budget.ok) return '这次已经做了很多事了，就先到这里吧。请调用 end_free_time 结束这次自由活动。'
      const signal = exec.signal
      const onAbort = () => void house.interrupt()
      signal?.addEventListener('abort', onAbort, { once: true })
      try {
        const r = await house.doScript(args.script, signal)
        const lowBudget = Number.isFinite(budget.left) && budget.left <= 5 ? `\n（这次还能行动 ${budget.left} 次）` : ''
        const over = house.windowOver(sessionId) ? '\n（自由活动时间到了。请调用 end_free_time。）' : ''
        return r.text + lowBudget + over
      } finally {
        signal?.removeEventListener('abort', onAbort)
      }
    },
  }))

  // house_render needs somewhere to keep the picture: only offered when the
  // deployment mounts an attachment store (the Web/Desktop profiles do).
  ctx.inject(['attachments'], (imageCtx) => {
    try {
      registerGlance(imageCtx, house)
    } catch (e) {
      house.log('warn', `house_render unavailable: ${e?.message ?? e}`)
    }
  })

  ctx.tools.register(defineTool({
    name: 'end_free_time',
    description: '结束这次自由活动（之后你的角色会自己去做一些日常事务）。note 可选：想在日记里留一句才写；这次已经用 diary_write 写过就不要再重复。',
    parameters: {
      note: { type: 'string', description: '可选：写进今天日记的一句话' },
    },
    output: textOutput,
    async execute(args, exec) {
      if (args.note && String(args.note).trim()) {
        await appendEntry(join(house.stateDir, 'diary'), new Date(), '小屋', args.note)
      }
      await house.rest(exec.agent?.id)
      exec.concludeTurn()
      return REST_TEXT
    },
  }))
}

/** Register house_render on a context that has the attachment store. */
function registerGlance(imageCtx, house) {
  imageCtx.tools.register(defineTool({
    name: 'house_render',
    description: '看一眼小屋现在的样子：返回一张整个家、院子和沙滩的静态像素画（你、团子、家具、菜地、天气和昼夜都画在上面）。每次都要在本机渲染一帧，本机算力有限，请只在需要时偶尔看一眼（一次自由活动最多一两次）；了解情况优先用 house_surroundings。',
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
