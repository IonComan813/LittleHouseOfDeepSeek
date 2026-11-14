// The resident's diary: one Markdown file per day, <stateDir>/diary/YYYY-MM-DD.md.
//
//   # 2026-11-13 周五
//
//   ### 13:05 · 小屋
//
//   去沙滩捡了贝壳……
//
// Entries come from any session (the house, QQ, ...); `source` says where.
// The model decides whether and what to write — nothing is logged here
// automatically. Pure file helpers, no host dependencies.

import { appendFile, mkdir, readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'

import { localDay } from './wake.js'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const DAY_RE = /^\d{4}-\d{2}-\d{2}$/
export const MAX_ENTRY_CHARS = 2000
export const MAX_READ_CHARS = 8000

/** @param {string} dir @param {string} day */
const dayFile = (dir, day) => join(dir, `${day}.md`)

/**
 * Append one entry to the day's diary file (creating it with a heading).
 * @param {string} dir @param {Date} at @param {string} source @param {string} text
 */
export async function appendEntry(dir, at, source, text, day = localDay(at)) {
  const body = String(text).trim()
  if (!body) throw new Error('日记内容是空的。')
  if (body.length > MAX_ENTRY_CHARS) throw new Error(`一条日记最多 ${MAX_ENTRY_CHARS} 个字。`)
  await mkdir(dir, { recursive: true })
  const file = dayFile(dir, day)
  let heading = ''
  try {
    await readFile(file, 'utf8')
  } catch {
    heading = `# ${day} ${WEEKDAYS[new Date(day + 'T12:00').getDay()]}\n\n`
  }
  const time = `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`
  await appendFile(file, `${heading}### ${time} · ${source}\n\n${body}\n\n`, 'utf8')
  return { day, time }
}

/** Days that have a diary, newest first. @param {string} dir */
export async function listDays(dir) {
  try {
    return (await readdir(dir)).filter((f) => DAY_RE.test(f.slice(0, -3)) && f.endsWith('.md')).map((f) => f.slice(0, -3)).sort().reverse()
  } catch {
    return []
  }
}

/**
 * Resolve "今天" / "昨天" / "today" / "yesterday" / "YYYY-MM-DD" to a day string.
 * @param {string | undefined} ref @param {Date} now
 */
export function resolveDay(ref, now) {
  const r = String(ref ?? '').trim().toLowerCase()
  if (!r || r === 'today' || r === '今天') return localDay(now)
  if (r === 'yesterday' || r === '昨天') return localDay(new Date(now.getTime() - 86_400_000))
  if (r === '前天') return localDay(new Date(now.getTime() - 2 * 86_400_000))
  if (DAY_RE.test(r)) return r
  return undefined
}

/** The day's diary text, or undefined. @param {string} dir @param {string} day */
export async function readDay(dir, day) {
  try {
    const text = await readFile(dayFile(dir, day), 'utf8')
    return text.length > MAX_READ_CHARS ? '……（前面省略）\n' + text.slice(-MAX_READ_CHARS) : text
  } catch {
    return undefined
  }
}

/** The newest entry's text across all days, or undefined. @param {string} dir */
export async function lastEntry(dir) {
  for (const day of await listDays(dir)) {
    const text = await readDay(dir, day)
    if (!text) continue
    const parts = text.split(/^### .*$/m)
    const last = parts[parts.length - 1]?.trim()
    if (last) return last
  }
  return undefined
}

/**
 * The newest entry with when it was written, for opening messages:
 * "（今天 10:05 写的）……" — so "上午" in it is not read as some other day.
 * @param {string} dir @param {Date} now
 */
export async function lastEntryNote(dir, now = new Date(), today = localDay(now)) {
  for (const day of await listDays(dir)) {
    const text = await readDay(dir, day)
    if (!text) continue
    const heads = [...text.matchAll(/^### (\d{2}:\d{2})[^\n]*$/gm)]
    const parts = text.split(/^### .*$/m)
    const last = parts[parts.length - 1]?.trim()
    if (!last) continue
    const time = heads.length ? heads[heads.length - 1][1] : ''
    const yesterday = localDay(new Date(new Date(today + 'T12:00').getTime() - 86_400_000))
    const when = day === today ? '今天' : day === yesterday ? '昨天' : day
    return `（${when}${time ? ' ' + time : ''} 写的）${last}`
  }
  return undefined
}
