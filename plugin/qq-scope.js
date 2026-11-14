// dsh-little-house/qq — mounted inside the `little-house-qq` agent preset: the
// QQ chats she has on her phone (one session per chat per day, see ../qq.js).
//
// Same persona as the life session, plus how QQ works. Tools: a read-only look
// at the house, a photo of the house sent to this chat, and the diary (sibling
// row). No shell, files or web — the same fail-closed guard as agent-scope.js.

import { defineTool } from '@deepseek-ai/dsh-tools'

import { DIARY_TOOLS } from './diary-scope.js'
import { COMMON_FACES, MAX_BUBBLES, SILENCE } from './lib/onebot.js'

export const name = 'little-house-qq-scope'
export const inject = ['tools', 'systemPrompt', 'littleHouse']

const OWN_TOOLS = new Set(['house_status', 'house_photo', ...DIARY_TOOLS])

function qqRules(ownerName) {
  return `## QQ
你住在潮汐湾的小屋里，这里是你手机上的 QQ：${ownerName}会私聊你，你也在几个群里。每个聊天每天一个对话，开头会告诉你日期、你在小屋里正在做什么。
- 收到的消息：私聊里是「${ownerName}：……」；群聊里是「[群名] 昵称：……」，${ownerName}在群里说话时标着（主人）。
  [图片] 是对方发来的图片（图片附在消息后面，你看得到），[表情包] 是表情包图片，[表情:名称] 是 QQ 表情，[语音]、[视频]、[文件] 你打不开。
  群里没叫你的消息不会单独发给你，下次有人叫你时会附上「群里刚才的消息」。
- 回复：直接写你要说的话，就是发出去的 QQ 消息。像平时用手机聊天一样：口语、简短，不用 Markdown、不用列表。
  想分成几条发，就用空行隔开（最多 ${MAX_BUBBLES} 条）。
  可以用 QQ 表情，写成 [表情:名称]，比如 [表情:微笑]。常用的有：${COMMON_FACES.join('、')}。别用太多，一两个就好。
- 群里不是每句话都要接。不想回、或者不是在跟你说话时，只写 ${SILENCE}。
- 在 QQ 上你不能在小屋里做事（做饭、种菜、钓鱼……要等自由活动时间）；可以聊你正在做的事、做过的事。
  house_status 能看看小屋现在的情况（时间、你在哪、团子、菜地……）；house_photo 拍一张小屋的照片发到这个聊天里。
- 聊天里有想记住的事，可以用 diary_write 写进日记（日记是你以后记得事情的依据）；diary_read 翻看以前的日记。
- 只说真实发生过的事，不编造小屋里没发生的事；不知道的就说不知道。`
}

export async function apply(ctx) {
  const house = ctx.littleHouse
  const persona = await house.personaText()

  const globalNames = ctx.tools.definitions().map((d) => d.name).filter((n) => !OWN_TOOLS.has(n))
  if (globalNames.length > 0) ctx.tools.restrict({ deny: globalNames })
  ctx.tools.guard((exec) => OWN_TOOLS.has(exec.name)
    ? undefined
    : `这里没有「${exec.name}」这个工具。你只能用 house_status、house_photo 和日记工具。`)
  ctx.systemPrompt.suppressRuntimeContext()
  ctx.systemPrompt.section({
    name: 'little-house:qq',
    order: 0,
    complete: true,
    interpolate: false,
    text: `${persona}\n\n${qqRules(house.config.qq.ownerName)}`,
  })

  const textOutput = {
    schema: { type: 'string' },
    render: (_args, value) => [{ type: 'text', text: value }],
  }

  ctx.tools.register(defineTool({
    name: 'house_status',
    description: '看看小屋现在的情况：时间、天气、你在哪、看到的东西、团子、你的状态和背包（只看，不行动）。',
    parameters: {},
    output: textOutput,
    async execute() {
      const look = await house.house.request('GET', '/look')
      return look.text
    },
  }))

  ctx.tools.register(defineTool({
    name: 'house_photo',
    description: '用手机拍一张小屋现在的照片（整个家、院子和沙滩），发到这个聊天里。caption 是随照片发的一句话，可以不写。拍照要用本机算力渲染，不要频繁拍。',
    parameters: {
      caption: { type: 'string', description: '随照片发的一句话（可选）' },
    },
    output: textOutput,
    async execute(args, exec) {
      const chat = house.qq?.chatOfSession(exec.agent?.id)
      if (!chat) return '现在发不了照片（找不到这个聊天）。'
      try {
        await house.qq.sendPhoto(chat.chatId, args.caption ? String(args.caption) : '')
        return '（照片发出去了。）'
      } catch (e) {
        return `照片没发出去：${e?.message ?? e}`
      }
    },
  }))
}
