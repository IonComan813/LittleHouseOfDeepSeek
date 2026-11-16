// Stickers she can send with phone_message: picture files whose names (without
// the extension) are what she writes, as [表情包:名字]. The plugin ships a set in
// plugin/stickers/ (qq.builtinStickers); the owner's own go in
// <stateDir>/stickers/ and win over a built-in one of the same name.
// Pure helpers, no host dependencies.

import { readdir } from 'node:fs/promises'
import { extname, join } from 'node:path'

export const STICKER_EXTS = ['.gif', '.png', '.jpg', '.jpeg', '.webp']
const TOKEN = /\[表情包[:：]([^\]]+)\]/g

/** name -> file path, from each folder in turn (later folders win). Missing folders are skipped. */
export async function listStickers(dirs) {
  const out = new Map()
  for (const dir of dirs) {
    let files = []
    try {
      files = await readdir(dir)
    } catch {
      continue
    }
    for (const f of files.sort()) {
      const ext = extname(f).toLowerCase()
      if (!STICKER_EXTS.includes(ext) || f.startsWith('.')) continue
      out.set(f.slice(0, -ext.length).normalize('NFC'), join(dir, f))
    }
  }
  return out
}

/**
 * Split one message into text and stickers, in order. Names must be written in
 * full; the ones that are not stickers are listed in `unknown` (nothing is sent then).
 * @returns {{ parts: ({ text: string } | { sticker: string })[], unknown: string[] }}
 */
export function splitStickers(text, names) {
  const parts = []
  const unknown = []
  let last = 0
  for (const m of String(text).matchAll(TOKEN)) {
    const before = text.slice(last, m.index).trim()
    if (before) parts.push({ text: before })
    const name = m[1].trim().normalize('NFC')
    if (names.has(name)) parts.push({ sticker: name })
    else unknown.push(name)
    last = m.index + m[0].length
  }
  const rest = text.slice(last).trim()
  if (rest) parts.push({ text: rest })
  return { parts, unknown }
}
