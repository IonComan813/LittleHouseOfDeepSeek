// OneBot 11 (NapCat) message helpers: pure functions, no host dependencies.
//
// Inbound: a message (segment array, or a CQ-code string as a fallback) becomes
// text the model reads — QQ faces as [表情:名称], pictures as [图片] plus the
// image URLs, @-mentions of her noted; voice, video and files are dropped. Outbound: her text becomes segments,
// [表情:名称] turning back into real QQ faces, blank lines into separate bubbles.

import { FACE_IDS, QQ_FACES } from './qq-faces.js'
import { dayOf } from './wake.js'

/** What she writes when she chooses not to answer (group chats). */
export const SILENCE = '[不回复]'
export const MAX_BUBBLES = 3

/** The faces suggested in her rules (all exist in QQ_FACES). */
export const COMMON_FACES = [
  '微笑', '呲牙', '偷笑', '可爱', '害羞', '调皮', '得意', '卖萌', '斜眼笑', '笑哭', 'doge', '疑问', '发呆', '尴尬',
  '委屈', '流泪', '大哭', '困', '睡', '哈欠', '晕', '吃', '托脸', '爱心', '玫瑰', '太阳', '月亮', '赞', 'OK', '拥抱',
].filter((n) => n in FACE_IDS)

/** 'private:123' / 'group:456' */
export function chatIdOf(event) {
  return event.message_type === 'group' ? `group:${event.group_id}` : `private:${event.user_id}`
}

/** @param {string} chatId */
export function splitChatId(chatId) {
  const [kind, target] = chatId.split(':')
  return { kind, target }
}

function unescapeCq(s) {
  return s.replace(/&#91;/g, '[').replace(/&#93;/g, ']').replace(/&#44;/g, ',').replace(/&amp;/g, '&')
}

/** A CQ-code string as a segment array (only for implementations that do not send arrays). */
export function cqToSegments(raw) {
  const out = []
  const re = /\[CQ:([a-zA-Z_]+)((?:,[^\]]*)?)\]/g
  let last = 0
  let m
  while ((m = re.exec(raw))) {
    if (m.index > last) out.push({ type: 'text', data: { text: unescapeCq(raw.slice(last, m.index)) } })
    const data = {}
    for (const kv of m[2].split(',').slice(1)) {
      const i = kv.indexOf('=')
      if (i > 0) data[kv.slice(0, i)] = unescapeCq(kv.slice(i + 1))
    }
    out.push({ type: m[1], data })
    last = re.lastIndex
  }
  if (last < raw.length) out.push({ type: 'text', data: { text: unescapeCq(raw.slice(last)) } })
  return out
}

/**
 * Read one inbound message.
 * @param {unknown} message segment array or CQ string
 * @param {string} selfId her QQ number ('' if unknown)
 * @returns {{ text: string, images: string[], mentioned: boolean, dropped: string[], replyTo?: string }}
 *   dropped: voice / video / file / forwarded / card segments, which are not passed on
 */
export function readMessage(message, selfId = '') {
  const segs = Array.isArray(message) ? message : cqToSegments(String(message ?? ''))
  let text = ''
  const images = []
  let mentioned = false
  let replyTo
  const dropped = []
  for (const seg of segs) {
    const d = seg?.data ?? {}
    switch (seg?.type) {
      case 'text':
        text += d.text ?? ''
        break
      case 'face':
        text += `[表情:${QQ_FACES[String(d.id)] ?? d.id}]`
        break
      case 'image':
      case 'mface': {
        const url = d.url || (/^https?:/.test(d.file ?? '') ? d.file : '')
        const label = seg.type === 'mface' || d.sub_type === 1 || d.summary === '[动画表情]' ? '[表情包]' : '[图片]'
        text += label
        if (url) images.push(url)
        break
      }
      case 'at':
        if (selfId && String(d.qq) === String(selfId)) mentioned = true
        else text += d.qq === 'all' ? '@全体成员 ' : `@${d.name || d.qq} `
        break
      case 'reply':
        replyTo = String(d.id ?? '')
        break
      case 'record':
      case 'video':
      case 'file':
      case 'forward':
      case 'json':
      case 'xml':
        dropped.push(seg.type) // stopped here: they never reach the model
        break
      default:
        if (seg?.type) text += `[${seg.type}]`
    }
  }
  return { text: text.trim(), images, mentioned, dropped, ...(replyTo ? { replyTo } : {}) }
}

/**
 * Her text as OneBot segments: [表情:名称] becomes a QQ face (unknown names stay text).
 * @param {string} text
 */
export function toSegments(text) {
  const out = []
  const re = /\[表情[:：]([^\]]+)\]/g
  let last = 0
  let m
  const pushText = (t) => {
    if (!t) return
    const prev = out[out.length - 1]
    if (prev?.type === 'text') prev.data.text += t
    else out.push({ type: 'text', data: { text: t } })
  }
  while ((m = re.exec(text))) {
    pushText(text.slice(last, m.index))
    const id = FACE_IDS[m[1].trim()]
    if (id !== undefined) out.push({ type: 'face', data: { id } })
    else pushText(m[0])
    last = re.lastIndex
  }
  pushText(text.slice(last))
  return out
}

/** Strip the Markdown a chat message should not have. */
export function plainText(text) {
  return String(text)
    .replace(/```[a-z]*\n?/gi, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/(^|\s)\*([^*\n]+)\*/g, '$1$2')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/`([^`]+)`/g, '$1')
    .trim()
}

/**
 * Her reply as QQ messages: blank lines separate bubbles (at most MAX_BUBBLES;
 * the rest joins the last one). [不回复] or nothing = no message.
 * @param {string} text
 * @returns {string[]}
 */
export function splitReply(text) {
  const clean = plainText(String(text ?? '').replaceAll(SILENCE, '')).trim()
  if (!clean) return []
  const parts = clean.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean)
  if (parts.length <= MAX_BUBBLES) return parts
  return [...parts.slice(0, MAX_BUBBLES - 1), parts.slice(MAX_BUBBLES - 1).join('\n')]
}

/** The day a QQ message belongs to (see wake.dayOf). */
export const qqDay = dayOf

/** @param {string} hhmm */
function minutesOf(hhmm) {
  const [h, m] = String(hhmm).split(':').map(Number)
  return h * 60 + (m || 0)
}

/** Whether `at` falls in [from, to) (HH:MM, may wrap past midnight). */
export function inHours(at, from, to) {
  const t = at.getHours() * 60 + at.getMinutes()
  const a = minutesOf(from)
  const b = minutesOf(to)
  return a <= b ? t >= a && t < b : t >= a || t < b
}

/**
 * One inbound line as the model reads it.
 * @param {{ group?: string, name: string, isOwner?: boolean, text: string }} m
 */
export function formatLine({ group, name, isOwner, text }) {
  const who = isOwner ? `${name}（主人）` : name
  return group ? `[${group}] ${who}：${text}` : `${name}：${text}`
}
