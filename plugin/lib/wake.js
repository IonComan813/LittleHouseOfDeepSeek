// Pure helpers for the random wake schedule. No host dependencies, so they can
// be unit-tested with `node --test`.

/**
 * Parse "HH:MM-HH:MM" into minutes-from-midnight. Empty string = no quiet hours.
 * @param {string} spec
 * @returns {{ start: number, end: number } | undefined}
 */
export function parseQuietHours(spec) {
  if (!spec || !spec.trim()) return undefined
  const m = /^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$/.exec(spec)
  if (!m) throw new Error(`quietHours must look like "23:30-07:30", got "${spec}"`)
  const [h1, m1, h2, m2] = m.slice(1).map(Number)
  if (h1 > 23 || h2 > 23 || m1 > 59 || m2 > 59) throw new Error(`quietHours out of range: "${spec}"`)
  return { start: h1 * 60 + m1, end: h2 * 60 + m2 }
}

/**
 * Whether `date` falls inside the quiet window (which may wrap midnight).
 * @param {Date} date
 * @param {{ start: number, end: number } | undefined} quiet
 */
export function inQuietHours(date, quiet) {
  if (!quiet || quiet.start === quiet.end) return false
  const t = date.getHours() * 60 + date.getMinutes()
  return quiet.start < quiet.end ? t >= quiet.start && t < quiet.end : t >= quiet.start || t < quiet.end
}

/**
 * Milliseconds until the quiet window ends (0 when not in it).
 * @param {Date} date
 * @param {{ start: number, end: number } | undefined} quiet
 */
export function msUntilQuietEnds(date, quiet) {
  if (!inQuietHours(date, quiet)) return 0
  const t = date.getHours() * 60 + date.getMinutes()
  let minutes = quiet.end - t
  if (minutes <= 0) minutes += 24 * 60
  return minutes * 60_000 - date.getSeconds() * 1000 - date.getMilliseconds()
}

/**
 * A random delay in [minMinutes, maxMinutes].
 * @param {number} minMinutes
 * @param {number} maxMinutes
 * @param {() => number} [random]
 */
export function randomDelayMs(minMinutes, maxMinutes, random = Math.random) {
  const lo = Math.max(0, Math.min(minMinutes, maxMinutes))
  const hi = Math.max(minMinutes, maxMinutes)
  return Math.round((lo + (hi - lo) * random()) * 60_000)
}

/** Local calendar date "YYYY-MM-DD". @param {Date} d */
export function localDay(d) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Human-friendly "3小时20分钟" for a duration. @param {number} ms */
export function formatDuration(ms) {
  const minutes = Math.floor(ms / 60_000)
  if (minutes < 1) return '不到一分钟'
  const d = Math.floor(minutes / 1440)
  const h = Math.floor((minutes % 1440) / 60)
  const m = minutes % 60
  return [d && `${d}天`, h && `${h}小时`, m && `${m}分钟`].filter(Boolean).join('')
}
