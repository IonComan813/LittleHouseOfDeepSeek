// QQ for the little house: one OneBot connection (NapCat), one DSH session per
// chat per day (`little-house-qq` preset), replies sent back as they are written.
//
// - Private chats with the owner (and listed friends); listed groups. In a group
//   she answers when @-mentioned, called by name or replied to; everything else
//   is kept as context for her next answer and in the day's transcript.
// - Days change at `rolloverHour` (04:00): a new session per chat per day, opened
//   with the date, what she is doing in the house and her latest diary entry.
// - At night (`night.from`–`night.to`) a message reaches her only with
//   probability `night.chance`; otherwise a short "asleep" reply goes out.
// - Free time in the house may end with a message to the owner (phone_message):
//   `sendToOwner`, at most `dailyShares` a day; the owner's next chat is told.
// - Every message in and out is appended to <stateDir>/qq/<day>.jsonl — the raw
//   material for memory (M4).

import { randomUUID } from 'node:crypto'
import { appendFile, mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

import { createUserMessage } from '@deepseek-ai/dsh-llm'

import { lastEntryNote } from './lib/diary.js'
import { OneBotClient } from './lib/onebot-client.js'
import { chatIdOf, formatLine, inHours, qqDay, readMessage, splitChatId, splitReply, toSegments } from './lib/onebot.js'
import { hhmm } from './lib/wake.js'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const MAX_IMAGE_BYTES = 8 * 1024 * 1024
const MAX_IMAGES_PER_TURN = 4
const GROUP_CONTEXT_LINES = 12
const SLEEP_REPLY_GAP_MS = 30 * 60_000
const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])

export class QQ {
  /** @param {import('./index.js').default} house the littleHouse service */
  constructor(house, config) {
    this.house = house
    this.config = config
    /** chatId -> { chatId, kind, target, label, day, sessionId, agent, pending, busy, opened, context } */
    this.chats = new Map()
    this.bySession = new Map()
    this.groupNames = new Map()
    this.sleepReplied = new Map()
    this.sentIds = []
    this.locks = new Map()
    this.client = new OneBotClient({
      url: config.url,
      token: config.accessToken,
      log: (level, msg) => house.log(level, msg),
      onEvent: (event) => void this.onEvent(event).catch((e) => house.log('warn', `QQ: ${e?.stack ?? e}`)),
    })
  }

  get dir() {
    return join(this.house.stateDir, 'qq')
  }

  get statePath() {
    return join(this.house.stateDir, 'qq-state.json')
  }

  start() {
    this.offEvents = this.house.ctx.on('session/event', (session, event) => this.onSessionEvent(session, event))
    this.client.start()
    this.house.log('info', `QQ: dialing ${this.config.url}`)
  }

  stop() {
    this.offEvents?.()
    this.client.stop()
  }

  get connected() {
    return this.client.connected
  }

  // ------------------------------------------------------------------ inbound

  async onEvent(event) {
    if (event.post_type !== 'message') return
    const userId = String(event.user_id ?? '')
    if (userId && userId === this.client.selfId) return
    const chatId = chatIdOf(event)
    const { kind, target } = splitChatId(chatId)
    const owner = String(this.config.ownerQQ || '')
    const isOwner = owner !== '' && userId === owner
    if (kind === 'private' && !isOwner && !this.config.friends.map(String).includes(userId)) return
    if (kind === 'group' && !this.config.groups.map(String).includes(target)) return

    const msg = readMessage(event.message ?? event.raw_message, this.client.selfId)
    const sender = event.sender ?? {}
    const name = kind === 'private'
      ? (isOwner ? this.config.ownerName : sender.nickname || userId)
      : sender.card || sender.nickname || userId
    const group = kind === 'group' ? await this.groupName(target) : undefined
    const label = kind === 'group' ? `群「${group}」` : name
    const line = formatLine({ group, name, isOwner: kind === 'group' && isOwner, text: msg.text || '[空消息]' })
    const addressed = kind === 'private' || msg.mentioned
      || this.config.names.some((n) => n && msg.text.includes(n))
      || (msg.replyTo !== undefined && this.sentIds.includes(msg.replyTo))
    await this.record({ chat: chatId, chatName: label, from: userId, name, text: msg.text, addressed })

    if (!addressed) {
      const chat = this.chats.get(chatId)
      const context = chat?.context ?? (this.pendingContext ??= new Map()).get(chatId) ?? []
      context.push(line)
      if (context.length > GROUP_CONTEXT_LINES) context.splice(0, context.length - GROUP_CONTEXT_LINES)
      if (!chat) this.pendingContext.set(chatId, context)
      return
    }

    const now = new Date()
    const night = inHours(now, this.config.night.from, this.config.night.to)
    if (night && Math.random() >= this.config.night.chance) {
      const last = this.sleepReplied.get(chatId) ?? 0
      if (this.config.night.reply && now.getTime() - last > SLEEP_REPLY_GAP_MS) {
        this.sleepReplied.set(chatId, now.getTime())
        await this.sendText(chatId, this.config.night.reply, { auto: true })
      }
      this.house.log('info', `QQ: ${chatId} at night, not woken`)
      return
    }
    await this.withLock(chatId, async () => {
      const chat = await this.chatFor(chatId, label)
      chat.pending.push({ line, images: msg.images, night, at: now })
      if (!chat.busy) await this.flush(chat)
    })
  }

  async withLock(key, fn) {
    const prev = this.locks.get(key) ?? Promise.resolve()
    const next = prev.then(fn, fn)
    this.locks.set(key, next.catch(() => {}))
    return next
  }

  async groupName(groupId) {
    if (this.groupNames.has(groupId)) return this.groupNames.get(groupId)
    let name = `群${groupId}`
    try {
      const info = await this.client.call('get_group_info', { group_id: Number(groupId) })
      if (info?.group_name) name = info.group_name
    } catch {
      // keep the fallback
    }
    this.groupNames.set(groupId, name)
    return name
  }

  // ------------------------------------------------------------------ sessions

  async readState() {
    try {
      return JSON.parse(await readFile(this.statePath, 'utf8'))
    } catch {
      return {}
    }
  }

  async writeState(state) {
    await mkdir(this.house.stateDir, { recursive: true })
    const tmp = this.statePath + '.tmp'
    await writeFile(tmp, JSON.stringify(state, null, 1), 'utf8')
    await rename(tmp, this.statePath)
  }

  /** Today's session for a chat (created at the first message after the day changes). */
  async chatFor(chatId, label) {
    const day = qqDay(new Date(), this.config.rolloverHour)
    const old = this.chats.get(chatId)
    if (old && old.day === day) return old
    const controller = this.house.ctx.get('sessionController')
    if (controller === undefined) throw new Error('sessionController is unavailable')
    const resolveAgent = async (sessionId) => {
      const resolved = await controller.resolveAgent(sessionId)
      if ('error' in resolved) throw resolved.error
      return resolved.agent
    }
    const state = await this.readState()
    const saved = state.sessions?.[chatId]
    let agent
    let opened = false
    if (saved && saved.day === day) {
      try {
        agent = await resolveAgent(saved.sessionId)
        opened = true
      } catch (e) {
        this.house.log('warn', `QQ: could not resume ${saved.sessionId}: ${e?.message ?? e}`)
      }
    }
    if (!agent) {
      const sessionId = `session-${randomUUID()}`
      const cwd = join(this.house.stateDir, 'workspace')
      await mkdir(cwd, { recursive: true })
      await controller.create({ sessionId, cwd, agentPreset: this.config.preset })
      agent = await resolveAgent(sessionId)
      try {
        this.house.ctx.get('sessionTitle')?.rename(agent.session, `QQ · ${label} · ${day}`)
      } catch {
        // a title is nice to have
      }
      const fresh = await this.readState()
      await this.writeState({ ...fresh, sessions: { ...(fresh.sessions ?? {}), [chatId]: { day, sessionId: agent.id } } })
      this.house.log('info', `QQ: new session ${agent.id} for ${chatId} (${day})`)
    }
    if (old) this.bySession.delete(old.sessionId)
    const { kind, target } = splitChatId(chatId)
    const context = old?.context ?? this.pendingContext?.get(chatId) ?? []
    this.pendingContext?.delete(chatId)
    const chat = { chatId, kind, target, label, day, sessionId: agent.id, agent, pending: [], busy: false, opened, context, texts: [] }
    this.chats.set(chatId, chat)
    this.bySession.set(agent.id, chatId)
    return chat
  }

  /** The chat a QQ session belongs to (for the tools). */
  chatOfSession(sessionId) {
    const chatId = this.bySession.get(sessionId)
    return chatId ? this.chats.get(chatId) : undefined
  }

  /** What opens a chat's session for the day. */
  async opening(chat) {
    const now = new Date()
    const lines = [`（${chat.day} ${WEEKDAYS[new Date(chat.day + 'T12:00').getDay()]}。这是今天和${chat.label}的 QQ 聊天。你在潮汐湾的小屋里，用手机收发消息。）`]
    try {
      const s = await this.house.house.request('GET', '/status')
      const where = `现在 ${hhmm(s.now * 1000)}，你在${s.location_name ?? '小屋'}`
      lines.push(s.free ? `${where}。现在是你的自由活动时间，你正在小屋里做自己的事。`
        : `${where}${s.idle ? '，' + s.idle.replace(/^在/, '') : ''}。`)
    } catch {
      lines.push(`现在 ${hhmm(now.getTime())}。`)
    }
    const note = await lastEntryNote(join(this.house.stateDir, 'diary'))
    if (note) lines.push(`日记里最近的一段：${note}`)
    return lines.join('\n')
  }

  async flush(chat) {
    const items = chat.pending.splice(0)
    if (!items.length) return
    const parts = []
    if (!chat.opened) {
      parts.push(await this.opening(chat), '')
      chat.opened = true
    }
    if (chat.kind === 'private' && String(chat.target) === String(this.config.ownerQQ)) {
      const unseen = await this.takeUnseen()
      if (unseen.length) parts.push('（之前你在小屋里用手机发给主人的消息：' + unseen.map((u) => `${u.time} 「${u.text}」`).join('；') + '）')
    }
    if (chat.context.length) {
      parts.push('（群里刚才的消息：）', ...chat.context.splice(0), '')
    }
    if (items.some((i) => i.night)) parts.push(`（现在是深夜 ${hhmm(Date.now())}，你本来在睡觉，被手机的提示音吵醒了。）`)
    parts.push(...items.map((i) => i.line))
    const images = await this.images(items.flatMap((i) => i.images).slice(0, MAX_IMAGES_PER_TURN))
    chat.busy = true
    chat.texts = []
    chat.agent.followup(createUserMessage({
      content: [{ type: 'text', text: parts.join('\n') }, ...images],
      source: { kind: 'little-house-qq' },
    }))
    await this.house.ctx.sessions.flush(chat.agent.session)
  }

  /** Download pictures and store them as image attachments the model can see. */
  async images(urls) {
    const store = this.house.ctx.get('attachments')
    if (!store || !urls.length) return []
    const out = []
    for (const url of urls) {
      try {
        const res = await fetch(url, { signal: AbortSignal.timeout(20_000) })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const type = (res.headers.get('content-type') || '').split(';')[0].trim()
        const data = Buffer.from(await res.arrayBuffer())
        if (data.length > MAX_IMAGE_BYTES) throw new Error('too large')
        const mediaType = IMAGE_TYPES.has(type) ? type : sniff(data)
        if (!mediaType) throw new Error(`not an image (${type})`)
        const ref = await store.saveImage({ data, mediaType, name: 'qq-image' })
        out.push({ type: 'image', attachment: ref })
      } catch (e) {
        this.house.log('warn', `QQ: could not fetch an image: ${e?.message ?? e}`)
      }
    }
    return out
  }

  // ------------------------------------------------------------------ outbound

  onSessionEvent(session, event) {
    const chatId = this.bySession.get(session?.id)
    if (!chatId) return
    const chat = this.chats.get(chatId)
    if (!chat || chat.sessionId !== session.id) return
    if (event.type === 'assistant/message') {
      const text = (event.data?.message?.content ?? []).filter((b) => b.type === 'text').map((b) => b.text).join('')
      if (text.trim()) void this.sendText(chatId, text).catch((e) => this.house.log('warn', `QQ: send failed: ${e?.message ?? e}`))
    } else if (event.type === 'turn/end') {
      chat.busy = false
      if (chat.pending.length) void this.withLock(chatId, () => (chat.busy ? undefined : this.flush(chat)))
    }
  }

  async sendSegments(chatId, message) {
    const { kind, target } = splitChatId(chatId)
    const r = kind === 'group'
      ? await this.client.call('send_group_msg', { group_id: Number(target), message })
      : await this.client.call('send_private_msg', { user_id: Number(target), message })
    if (r?.message_id !== undefined) {
      this.sentIds.push(String(r.message_id))
      if (this.sentIds.length > 200) this.sentIds.splice(0, 100)
    }
  }

  /** Send her text to a chat (blank lines = separate messages). */
  async sendText(chatId, text, meta = {}) {
    const bubbles = splitReply(text)
    for (const b of bubbles) {
      await this.sendSegments(chatId, toSegments(b))
      await this.record({ chat: chatId, from: 'me', name: '她', text: b, out: true, ...meta })
    }
    return bubbles.length
  }

  /** A picture of the house as a OneBot image segment. */
  async photoSegment() {
    const png = await this.house.house.requestBytes('/screenshot?scale=2')
    return { type: 'image', data: { file: 'base64://' + Buffer.from(png).toString('base64') } }
  }

  async sendPhoto(chatId, caption = '') {
    const message = [...(caption ? toSegments(caption) : []), await this.photoSegment()]
    await this.sendSegments(chatId, message)
    await this.record({ chat: chatId, from: 'me', name: '她', text: (caption ? caption + ' ' : '') + '[小屋的照片]', out: true })
  }

  /** How many messages she may still send the owner today on her own. */
  async sharesLeft() {
    const state = await this.readState()
    const day = qqDay(new Date(), this.config.rolloverHour)
    const used = state.shares?.day === day ? state.shares.count : 0
    return Math.max(0, this.config.dailyShares - used)
  }

  /** Whether she can message the owner on her own right now. */
  async canShare() {
    return Boolean(this.config.ownerQQ) && this.connected && (await this.sharesLeft()) > 0
  }

  /** phone_message from the house: a message (maybe with a photo) to the owner. */
  async sendToOwner(text, photo = false) {
    if (!this.config.ownerQQ) throw new Error('还没有设置主人的 QQ。')
    if (!this.connected) throw new Error('手机现在没有信号（QQ 没有连上）。')
    if ((await this.sharesLeft()) <= 0) throw new Error('今天已经给主人发过好几条消息了，留到明天吧。')
    const chatId = `private:${this.config.ownerQQ}`
    const bubbles = splitReply(text)
    if (!bubbles.length && !photo) throw new Error('消息是空的。')
    for (const [i, b] of bubbles.entries()) {
      const segs = toSegments(b)
      if (photo && i === bubbles.length - 1) segs.push(await this.photoSegment())
      await this.sendSegments(chatId, segs)
    }
    if (!bubbles.length) await this.sendSegments(chatId, [await this.photoSegment()])
    const shown = bubbles.join(' / ') + (photo ? ' [小屋的照片]' : '')
    await this.record({ chat: chatId, from: 'me', name: '她', text: shown, out: true, proactive: true })
    const state = await this.readState()
    const day = qqDay(new Date(), this.config.rolloverHour)
    const count = (state.shares?.day === day ? state.shares.count : 0) + 1
    const unseen = [...(state.unseen ?? []), { time: hhmm(Date.now()), text: shown }].slice(-5)
    await this.writeState({ ...state, shares: { day, count }, unseen })
    this.house.log('info', `QQ: she messaged the owner (${count} today)`)
  }

  async takeUnseen() {
    const state = await this.readState()
    if (!state.unseen?.length) return []
    await this.writeState({ ...state, unseen: [] })
    return state.unseen
  }

  // ------------------------------------------------------------------ transcript

  async record(entry) {
    try {
      await mkdir(this.dir, { recursive: true })
      const now = new Date()
      const line = JSON.stringify({ t: now.toISOString(), ...entry })
      await appendFile(join(this.dir, `${qqDay(now, this.config.rolloverHour)}.jsonl`), line + '\n', 'utf8')
    } catch (e) {
      this.house.log('warn', `QQ: could not record a message: ${e?.message ?? e}`)
    }
  }
}

/** Image type from the first bytes (QQ's CDN does not always say). */
function sniff(b) {
  if (b[0] === 0x89 && b[1] === 0x50) return 'image/png'
  if (b[0] === 0xff && b[1] === 0xd8) return 'image/jpeg'
  if (b[0] === 0x47 && b[1] === 0x49) return 'image/gif'
  if (b.slice(8, 12).toString('latin1') === 'WEBP') return 'image/webp'
  return undefined
}
