// QQ on her phone: one OneBot connection to NapCat. Messages go into her day
// session (the same one as her free time in the house) as "the phone buzzed";
// she answers with the phone_message tool — whatever else she writes is not sent.
//
// - Private chats with the owner (and listed friends), any time she is awake.
// - Voice, video and files are stopped here: they never reach the model. A
//   message with nothing else in it is only recorded.
// - While she sleeps (bedtime until her first free time) nothing reaches her;
//   `sleepReply` goes out instead (at most once per chat per half hour).
// - Every message in and out is appended to <stateDir>/qq/<day>.jsonl — the raw
//   material for memory.
//
// Group chats are switched off for now (owner's decision, 2026-11-14). The code
// that handled them is kept below as comments.

import { appendFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'

import { OneBotClient } from './lib/onebot-client.js'
import { chatIdOf, formatLine, readMessage, splitChatId, splitReply, toSegments } from './lib/onebot.js'

const MAX_IMAGE_BYTES = 8 * 1024 * 1024
const MAX_IMAGES_PER_MESSAGE = 4
const SLEEP_REPLY_GAP_MS = 30 * 60_000
const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])
const DROPPED_NAMES = { record: '语音', video: '视频', file: '文件', forward: '聊天记录', json: '卡片', xml: '卡片' }
// const GROUP_CONTEXT_LINES = 12

export class QQ {
  /** @param {import('./index.js').default} house the littleHouse service */
  constructor(house, config) {
    this.house = house
    this.config = config
    /** name -> QQ number, for phone_message(to) */
    this.contacts = new Map()
    if (config.ownerQQ) this.contacts.set(config.ownerName, String(config.ownerQQ))
    this.sleepReplied = new Map()
    // this.groupNames = new Map()
    // this.groupContext = new Map()
    // this.sentIds = []
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

  start() {
    this.client.start()
    this.house.log('info', `QQ: dialing ${this.config.url}`)
  }

  stop() {
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
    const { kind } = splitChatId(chatId)
    if (kind !== 'private') return // group chats are off for now (see the comment at the top)
    const owner = String(this.config.ownerQQ || '')
    const isOwner = owner !== '' && userId === owner
    if (!isOwner && !this.config.friends.map(String).includes(userId)) return

    const msg = readMessage(event.message ?? event.raw_message, this.client.selfId)
    const sender = event.sender ?? {}
    const name = isOwner ? this.config.ownerName : sender.nickname || userId
    if (!isOwner) this.contacts.set(name, userId)
    const dropped = msg.dropped.map((t) => DROPPED_NAMES[t] ?? t)
    await this.record({ chat: chatId, from: userId, name, text: [msg.text, ...dropped.map((d) => `[${d}]`)].filter(Boolean).join(' ') })
    if (!msg.text && !msg.images.length) return // only voice / video / files: stopped here

    // Group chats (off for now):
    // const group = kind === 'group' ? await this.groupName(target) : undefined
    // const addressed = kind === 'private' || msg.mentioned
    //   || this.config.names.some((n) => n && msg.text.includes(n))
    //   || (msg.replyTo !== undefined && this.sentIds.includes(msg.replyTo))
    // if (!addressed) { keep the line in this.groupContext (at most GROUP_CONTEXT_LINES) and return }

    const now = Date.now()
    if (await this.house.isAsleep(now)) {
      const last = this.sleepReplied.get(chatId) ?? 0
      if (this.config.sleepReply && now - last > SLEEP_REPLY_GAP_MS) {
        this.sleepReplied.set(chatId, now)
        await this.sendText(chatId, this.config.sleepReply, { auto: true })
      }
      this.house.log('info', `QQ: ${chatId} while she sleeps: not passed on`)
      return
    }
    const line = formatLine({ name, text: msg.text || '[图片]' })
    const images = await this.images(msg.images.slice(0, MAX_IMAGES_PER_MESSAGE))
    await this.house.phoneBuzz({ line, images })
  }

  // async groupName(groupId) {
  //   get_group_info → group_name, cached in this.groupNames; fallback `群${groupId}`
  // }

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

  async sendSegments(chatId, message) {
    const { kind, target } = splitChatId(chatId)
    return kind === 'group'
      ? this.client.call('send_group_msg', { group_id: Number(target), message })
      : this.client.call('send_private_msg', { user_id: Number(target), message })
  }

  /** Send text to a chat (blank lines = separate messages). */
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

  /** The QQ number for a name she writes in phone_message(to) ('' = the owner). */
  resolveContact(to) {
    const name = String(to ?? '').trim()
    if (!name || name === this.config.ownerName || name === '主人') return String(this.config.ownerQQ || '')
    return this.contacts.get(name) ?? (/^\d{5,}$/.test(name) ? name : '')
  }

  /** phone_message: send her message (maybe with a photo of the house). */
  async phoneMessage(text, { photo = false, to = '' } = {}) {
    if (!this.connected) throw new Error('手机现在没有信号（QQ 没有连上）。')
    const qq = this.resolveContact(to)
    if (!qq) {
      const known = [...this.contacts.keys()].join('、') || this.config.ownerName
      throw new Error(`联系人里没有「${to}」。能发给：${known}。`)
    }
    if (qq !== String(this.config.ownerQQ) && !this.config.friends.map(String).includes(qq)) throw new Error('只能发给主人和联系人里的朋友。')
    const chatId = `private:${qq}`
    const bubbles = splitReply(text)
    if (!bubbles.length && !photo) throw new Error('消息是空的。')
    for (const [i, b] of bubbles.entries()) {
      const segs = toSegments(b)
      if (photo && i === bubbles.length - 1) segs.push(await this.photoSegment())
      await this.sendSegments(chatId, segs)
    }
    if (!bubbles.length) await this.sendSegments(chatId, [await this.photoSegment()])
    const shown = bubbles.join(' / ') + (photo ? ' [小屋的照片]' : '')
    await this.record({ chat: chatId, from: 'me', name: '她', text: shown, out: true })
    return bubbles.length + (photo && !bubbles.length ? 1 : 0)
  }

  // ------------------------------------------------------------------ transcript

  async record(entry) {
    try {
      await mkdir(this.dir, { recursive: true })
      const now = new Date()
      const line = JSON.stringify({ t: now.toISOString(), ...entry })
      await appendFile(join(this.dir, `${this.house.dayKey(now)}.jsonl`), line + '\n', 'utf8')
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
