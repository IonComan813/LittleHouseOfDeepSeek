// dsh-little-house — host-level plugin.
//
// Provides the `littleHouse` service: it keeps the Python house process alive,
// opens the resident's free-time slots on a daily schedule (breakfast, lunch,
// dinner, maybe late evening) in a dedicated "life" session (which runs the
// `little-house` agent preset), and hands the agent-scoped tools in
// ./agent-scope.js their house client, budget and free-time window.
//
// Outside free time the house itself keeps her living her everyday life.

import { appendFileSync, existsSync, mkdirSync, renameSync, statSync } from 'node:fs'
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { randomUUID } from 'node:crypto'

import { Service } from '@deepseek-ai/cordis'
import Schema from '@deepseek-ai/schemastery'
import { createUserMessage } from '@deepseek-ai/dsh-llm'

import { lastEntry } from './lib/diary.js'
import { HouseProcess } from './lib/house-process.js'
import { DEFAULT_SLOTS } from './lib/slots.js'
import {
  TIME_UP_TEXT, buildNudge, buildWakeMessage, checkSlots, findSlot, formatDuration, hhmm, localDay, localIso, planDay, recapEvents,
} from './lib/wake.js'

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url))
const DEFAULT_HOUSE_DIR = resolve(PLUGIN_DIR, '..', 'house')
const DEFAULT_STATE_DIR = join(homedir(), '.dsh', 'little-house')

export const name = 'little-house'

const MAX_LOG_BYTES = 1024 * 1024
const DO_CHUNK_SECONDS = 240 // one /do or /report request waits at most this long (Node's fetch gives up after 5 min)
const NUDGE_DELAY_MS = 2 * 60_000
const MIN_SLOT_MINUTES = 5

/** Identifies one slot on one day, e.g. "2026-11-14 早上". */
function slotKey(plan) {
  return `${localDay(new Date(plan.start))} ${plan.name}`
}

export default class LittleHouse extends Service {
  static inject = ['agents', 'sessions']

  static Config = Schema.object({
    stateDir: Schema.string().default('').description('存档与状态目录；留空 = ~/.dsh/little-house'),
    personaFile: Schema.string().default('').description('人设文件（Markdown）；留空 = 插件自带的示例人设'),
    house: Schema.object({
      dir: Schema.string().default('').description('house/ 目录；留空 = 插件旁边的 ../house'),
      python: Schema.string().default(process.platform === 'win32' ? 'python' : 'python3').description('Python 可执行文件'),
      port: Schema.natural().default(8770).description('小屋本地端口（只监听 127.0.0.1）'),
      autoStart: Schema.boolean().default(true).description('需要时自动启动小屋进程'),
      window: Schema.boolean().default(false).description('启动时打开只读动画窗口（需要 pygame-ce；关掉窗口不影响小屋）'),
    }).default({}),
    wake: Schema.object({
      enabled: Schema.boolean().default(true),
      slots: Schema.array(Schema.object({
        name: Schema.string().required().description('时段名，会告诉她，例如「早上」'),
        from: Schema.string().required().description('最早开始时间 HH:MM'),
        to: Schema.string().required().description('最晚开始时间 HH:MM（和 from 相同 = 固定时间）'),
        minutes: Schema.number().min(1).default(40).description('自由活动多少分钟'),
        chance: Schema.number().min(0).max(1).default(1).description('这个时段当天出现的概率'),
      })).default(DEFAULT_SLOTS).description('每天的自由活动时段：在 from–to 之间随机挑一个开始时间（每天投一次）'),
      firstWakeDelaySeconds: Schema.natural().default(0).description('测试用：DSH 启动后过多少秒先来一次临时的自由活动（0 = 只按作息表）'),
      testMinutes: Schema.number().min(1).default(40).description('测试用的临时自由活动有多少分钟'),
      maxActionsPerWake: Schema.natural().default(40).description('每次自由活动最多调用多少次 house_do（安全上限；平时由时间约束）'),
      maxNudges: Schema.natural().default(2).description('她提前停下但时间还没到时，最多再叫她几次'),
    }).default({}),
    session: Schema.object({
      agentPreset: Schema.string().default('little-house'),
      title: Schema.string().default('小屋生活'),
    }).default({}),
  })

  constructor(ctx, config) {
    super(ctx, 'littleHouse')
    this.config = config
    this.stateDir = config.stateDir || DEFAULT_STATE_DIR
    try {
      mkdirSync(this.stateDir, { recursive: true })
    } catch {
      // reported on first use
    }
    this.house = new HouseProcess({
      python: config.house.python,
      houseDir: config.house.dir || DEFAULT_HOUSE_DIR,
      stateDir: join(this.stateDir, 'world'),
      port: config.house.port,
      autoStart: config.house.autoStart,
      log: (level, msg) => this.log(level, msg),
    })
    this.slots = checkSlots(config.wake.slots ?? DEFAULT_SLOTS)
    this.wakeTimer = undefined
    this.waking = false
    /** Per-session budget for the current free time: sessionId -> { actions, max } */
    this.budgets = new Map()
    /** Per-session free-time window: sessionId -> { until, name, ended, rested, nudges, timer } */
    this.windows = new Map()

    ctx.effect(() => {
      const boot = setTimeout(() => {
        this.start().catch((e) => this.log('warn', `start failed: ${e?.stack ?? e}`))
      }, 0)
      return () => {
        clearTimeout(boot)
        clearTimeout(this.wakeTimer)
        for (const w of this.windows.values()) {
          clearTimeout(w.timer)
          clearTimeout(w.nudgeTimer)
        }
        void this.house.dispose()
      }
    })
  }

  log(level, msg) {
    if (level === 'debug' && !process.env.LH_DEBUG) return
    const logger = this.ctx.logger
    const fn = logger?.[level] ?? logger?.info
    if (typeof fn === 'function') fn.call(logger, `little-house: ${msg}`)
    else console.log(`[little-house] ${msg}`)
    // Also keep our own log next to the save: DSH's logger is not always visible
    // (e.g. the Desktop app), and this is where to look when something is off.
    try {
      const file = join(this.stateDir, 'plugin.log')
      if (existsSync(file) && statSync(file).size > MAX_LOG_BYTES) renameSync(file, file + '.1')
      appendFileSync(file, `${new Date().toISOString()} ${level.toUpperCase()} ${msg}\n`, 'utf8')
    } catch {
      // logging must never break the plugin
    }
  }

  async start() {
    await mkdir(this.stateDir, { recursive: true })
    try {
      await this.house.ensure()
      this.log('info', 'house is up')
      // A free time left open by a previous run (DSH quit mid-slot) is over:
      // nobody is driving her. If the slot is still running it reopens below.
      await this.house.request('POST', '/session', { free_until: 0 })
      if (this.config.house.window) {
        try {
          await this.house.request('POST', '/window', { open: true })
        } catch (e) {
          this.log('warn', `could not open the house window: ${e.message}`)
        }
      }
    } catch (e) {
      this.log('warn', `house not available yet: ${e.message}`)
    }
    if (!this.config.wake.enabled) return
    if (this.config.wake.firstWakeDelaySeconds > 0) {
      const delay = this.config.wake.firstWakeDelaySeconds * 1000
      this.log('info', `test free time in ${formatDuration(delay)}`)
      setTimeout(() => {
        const start = Date.now()
        this.wake({ name: '临时', start, minutes: this.config.wake.testMinutes }, start + this.config.wake.testMinutes * 60_000)
          .catch((e) => this.log('warn', `wake failed: ${e?.stack ?? e}`))
      }, delay)
    }
    await this.schedule()
  }

  // ------------------------------------------------------------------ persona

  async personaText() {
    const file = this.config.personaFile || join(PLUGIN_DIR, 'persona', 'default.md')
    try {
      return (await readFile(file, 'utf8')).trim()
    } catch (e) {
      this.log('warn', `persona file unreadable (${file}): ${e.message}`)
      return '你是住在一间海边小屋里的居民。'
    }
  }

  // ------------------------------------------------------------------ state

  get statePath() {
    return join(this.stateDir, 'plugin-state.json')
  }

  async readState() {
    try {
      return JSON.parse(await readFile(this.statePath, 'utf8'))
    } catch {
      return {}
    }
  }

  async writeState(state) {
    await mkdir(this.stateDir, { recursive: true })
    const tmp = this.statePath + '.tmp'
    await writeFile(tmp, JSON.stringify(state, null, 1), 'utf8')
    await rename(tmp, this.statePath)
  }

  /** Today's and tomorrow's plans, rolled once per day and remembered across restarts. */
  async plans(now = new Date()) {
    const state = await this.readState()
    const days = [now, new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)].map(localDay)
    const kept = {}
    let changed = false
    for (const [i, day] of days.entries()) {
      const old = state.plans?.[day]
      if (old) kept[day] = old
      else {
        kept[day] = planDay(i === 0 ? now : new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1), this.slots)
        changed = true
      }
    }
    if (changed || Object.keys(state.plans ?? {}).length !== days.length) {
      await this.writeState({ ...state, plans: kept })
      const today = kept[days[0]].map((p) => `${p.name} ${hhmm(p.start)}`).join('、') || '（无）'
      this.log('info', `free time today: ${today}`)
    }
    return [...kept[days[0]], ...kept[days[1]]]
  }

  // ------------------------------------------------------------------ schedule

  async schedule() {
    clearTimeout(this.wakeTimer)
    const now = Date.now()
    const done = new Set((await this.readState()).doneSlots ?? [])
    const plans = (await this.plans(new Date(now))).filter((p) => !done.has(slotKey(p)))
    const found = findSlot(now, plans, MIN_SLOT_MINUTES)
    if (!found) {
      // nothing left today or tomorrow (every slot rolled "no"): look again in a few hours
      this.wakeTimer = setTimeout(() => void this.schedule(), 6 * 3600_000)
      return
    }
    const delay = found.active ? 0 : found.plan.start - now
    this.log('info', `next free time: ${found.plan.name} at ${new Date(now + delay).toLocaleString()} until ${hhmm(found.until)}`)
    this.wakeTimer = setTimeout(() => {
      this.wake(found.plan, found.until, found.active)
        .catch((e) => this.log('warn', `wake failed: ${e?.stack ?? e}`))
        .finally(() => {
          // the next slot is computed after this one is over
          const wait = Math.max(1_000, found.until - Date.now() + 1_000)
          this.wakeTimer = setTimeout(() => void this.schedule(), wait)
        })
    }, delay)
  }

  /**
   * Open one free-time slot. Returns a short status string.
   * @param {{ name: string, start: number, minutes: number }} plan
   * @param {number} until epoch ms when the slot ends
   * @param {boolean} [resumed] the slot had already started (e.g. DSH started mid-slot)
   */
  async wake(plan, until, resumed = false) {
    if (this.waking) return 'busy: a wake is already being delivered'
    this.waking = true
    try {
      const now = new Date()
      const state = await this.readState()
      const today = localDay(now)
      const agent = await this.lifeAgent(state, today)
      if (agent.status !== 'idle') {
        this.log('info', `life session ${agent.id} is busy (${agent.status}); skipping ${plan.name}`)
        return 'skipped: agent busy'
      }

      // All times she is told come from the house's game clock (the same one the
      // picture and house_do results use), not from this process's clock.
      const skew = await this.clockSkew()
      const session = await this.house.request('POST', '/session', { free_until: (until + skew) / 1000 })
      const look = await this.house.request('GET', '/look')
      const lastWake = state.lastWakeAt ? new Date(state.lastWakeAt) : undefined
      const lastRest = state.lastRestAt ? new Date(state.lastRestAt) : lastWake
      let news = []
      let recap = []
      try {
        if (lastRest) {
          news = (await this.house.request('GET', `/news?since=${encodeURIComponent(localIso(lastRest))}`)).news ?? []
        }
        if (lastWake) {
          const since = encodeURIComponent(localIso(lastWake))
          recap = recapEvents((await this.house.request('GET', `/events?since=${since}&actor=resident`)).events ?? [])
        }
      } catch (e) {
        this.log('warn', `could not read house news: ${e.message}`)
      }

      this.openWindow(agent, plan, until)
      const text = buildWakeMessage({
        slotName: plan.name,
        start: now.getTime() + skew,
        until: until + skew,
        before: session.before,
        recap,
        news: news.map((n) => n.text),
        lastNote: await this.lastDiaryNote(),
        look: look.text,
        resumed,
      })
      await this.send(agent, text)
      await this.writeState({ ...(await this.readState()), lastWakeAt: now.toISOString() })
      this.log('info', `free time (${plan.name}, until ${hhmm(until)}) in session ${agent.id}`)
      return `woke: ${agent.id}`
    } finally {
      this.waking = false
    }
  }

  /** Milliseconds the house's game clock is ahead of this process's clock (0 in normal use). */
  async clockSkew() {
    try {
      const status = await this.house.request('GET', '/status')
      return typeof status.now === 'number' ? Math.round(status.now * 1000 - Date.now()) : 0
    } catch {
      return 0
    }
  }

  async send(agent, text) {
    agent.followup(createUserMessage({ content: [{ type: 'text', text }], source: { kind: 'little-house' } }))
    await this.ctx.sessions.flush(agent.session)
    void agent.whenIdle().then(
      () => this.onIdle(agent),
      (e) => this.log('warn', `life turn ended with error: ${e}`),
    )
  }

  // ------------------------------------------------------------------ the free-time window

  openWindow(agent, plan, until) {
    const old = this.windows.get(agent.id)
    if (old) {
      clearTimeout(old.timer)
      clearTimeout(old.nudgeTimer)
    }
    const win = { name: plan.name, key: slotKey(plan), until, agent, ended: false, rested: false, diary: false, nudges: 0, timer: undefined, nudgeTimer: undefined }
    win.timer = setTimeout(() => void this.timeUp(agent.id), Math.max(0, until - Date.now()))
    this.windows.set(agent.id, win)
    this.budgets.set(agent.id, { actions: 0, max: this.config.wake.maxActionsPerWake })
  }

  /** The free-time window of a session, if one is open. */
  window(sessionId) {
    const w = this.windows.get(sessionId)
    return w && !w.ended ? w : undefined
  }

  /** Whether this session has (or had) a free-time window. */
  hasWindow(sessionId) {
    return this.windows.has(sessionId)
  }

  /** Whether she wrote her diary during this session's current (or just ended) free time. */
  diaryWritten(sessionId) {
    return Boolean(this.windows.get(sessionId)?.diary)
  }

  /**
   * diary_write was called: remember it for end_free_time and say which free time it belongs to.
   * @returns {string | undefined} the slot name ("早上"), if the session has free time
   */
  markDiary(sessionId) {
    const w = this.windows.get(sessionId)
    if (!w) return undefined
    w.diary = true
    return w.name
  }

  /** Free time ran out. If she is idle and has not written her diary, ask her to. */
  async timeUp(sessionId) {
    const w = this.windows.get(sessionId)
    await this.endWindow(sessionId, 'time is up')
    if (!w || w.rested || w.diary || w.agent?.status !== 'idle') return
    try {
      await this.send(w.agent, TIME_UP_TEXT)
      this.log('info', `asked for the diary at the end of ${w.name} (session ${sessionId})`)
    } catch (e) {
      this.log('warn', `could not ask for the diary: ${e?.message ?? e}`)
    }
  }

  /** Whether this session had free time that is now over. */
  windowOver(sessionId) {
    const w = this.windows.get(sessionId)
    return Boolean(w && w.ended)
  }

  minutesLeft(sessionId) {
    const w = this.window(sessionId)
    return w ? Math.max(0, Math.round((w.until - Date.now()) / 60_000)) : 0
  }

  async endWindow(sessionId, reason) {
    const w = this.windows.get(sessionId)
    if (!w || w.ended) return
    w.ended = true
    clearTimeout(w.timer)
    clearTimeout(w.nudgeTimer)
    try {
      await this.house.request('POST', '/session', { free_until: 0 })
    } catch (e) {
      this.log('warn', `could not end free time in the house: ${e.message}`)
    }
    const state = await this.readState()
    const doneSlots = [...(state.doneSlots ?? []), w.key].slice(-20)
    await this.writeState({ ...state, lastRestAt: new Date().toISOString(), doneSlots })
    this.log('info', `free time (${w.name}) over in session ${sessionId}: ${reason}`)
  }

  /** end_free_time: she ends her free time herself. */
  async endFreeTime(sessionId) {
    const w = this.windows.get(sessionId)
    if (w) w.rested = true
    await this.endWindow(sessionId, 'she went to rest')
  }

  /** Her turn ended. If she stopped early without end_free_time, look in on her a bit later. */
  onIdle(agent) {
    const w = this.window(agent.id)
    if (!w || w.rested) return
    if (w.nudges >= this.config.wake.maxNudges) {
      this.log('info', `she stopped early; no more nudges (session ${agent.id})`)
      return
    }
    clearTimeout(w.nudgeTimer)
    w.nudgeTimer = setTimeout(async () => {
      try {
        const left = this.minutesLeft(agent.id)
        if (!this.window(agent.id) || left < MIN_SLOT_MINUTES || agent.status !== 'idle') return
        w.nudges += 1
        const look = await this.house.request('GET', '/look')
        await this.send(agent, buildNudge({ left, look: look.text }))
        this.log('info', `nudged (${w.nudges}) with ${left} min left in session ${agent.id}`)
      } catch (e) {
        this.log('warn', `nudge failed: ${e?.message ?? e}`)
      }
    }, NUDGE_DELAY_MS)
  }

  /** The newest diary entry from any session, if any. */
  async lastDiaryNote() {
    return lastEntry(join(this.stateDir, 'diary'))
  }

  /** The live Agent of today's life session, creating the session when needed. */
  async lifeAgent(state, today) {
    const controller = this.ctx.get('sessionController')
    if (controller === undefined) throw new Error('sessionController is unavailable (is this the Web/Desktop profile?)')
    const resolveAgent = async (sessionId) => {
      const resolved = await controller.resolveAgent(sessionId)
      if ('error' in resolved) throw resolved.error
      return resolved.agent
    }
    if (state.lifeSessionId && state.lifeSessionDay === today) {
      try {
        return await resolveAgent(state.lifeSessionId)
      } catch (e) {
        this.log('warn', `could not resume life session ${state.lifeSessionId}: ${e?.message ?? e}; creating a new one`)
      }
    }
    const sessionId = `session-${randomUUID()}`
    const workDir = join(this.stateDir, 'workspace')
    await mkdir(workDir, { recursive: true })
    await controller.create({ sessionId, cwd: workDir, agentPreset: this.config.session.agentPreset })
    const agent = await resolveAgent(sessionId)
    try {
      this.ctx.get('sessionTitle')?.rename(agent.session, `${this.config.session.title} · ${today}`)
    } catch (e) {
      this.log('warn', `could not title the life session: ${e?.message ?? e}`)
    }
    await this.writeState({ ...(await this.readState()), lifeSessionId: agent.id, lifeSessionDay: today })
    this.log('info', `created life session ${agent.id}`)
    return agent
  }

  // ------------------------------------------------------------------ tool support

  /** Count one house_do call against the current free time's budget. */
  takeAction(sessionId) {
    const b = this.budgets.get(sessionId)
    if (!b) return { ok: true, left: Infinity }
    if (b.actions >= b.max) return { ok: false, left: 0 }
    b.actions += 1
    return { ok: true, left: b.max - b.actions }
  }

  /**
   * Run a script in the house in real time, waiting for it in chunks (each
   * HTTP request stays well under Node's five-minute limit). Stops the script
   * if `signal` aborts (the turn was cancelled).
   * @param {string} script
   * @param {AbortSignal} [signal]
   */
  async doScript(script, signal) {
    const timeoutMs = (DO_CHUNK_SECONDS + 30) * 1000
    let r = await this.house.request('POST', '/do', { script, wait: DO_CHUNK_SECONDS }, { timeoutMs, signal })
    while (!r.done && !signal?.aborted) {
      r = await this.house.request('POST', '/report', { id: r.id, wait: DO_CHUNK_SECONDS }, { timeoutMs, signal })
    }
    return r
  }

  async interrupt() {
    try {
      await this.house.request('POST', '/interrupt', {})
    } catch (e) {
      this.log('warn', `could not interrupt: ${e.message}`)
    }
  }
}
