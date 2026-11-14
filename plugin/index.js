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
import { appendFile, mkdir, readFile, readdir, writeFile, rename } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { randomUUID } from 'node:crypto'

import { Service } from '@deepseek-ai/cordis'
import Schema from '@deepseek-ai/schemastery'
import { createUserMessage } from '@deepseek-ai/dsh-llm'

import { lastEntryNote } from './lib/diary.js'
import { buildSummaryPrompt, emptyMemory, forget, formatChats, formatTranscript, mergeDay, parseReply, render as renderMemory } from './lib/memory.js'
import { HouseProcess } from './lib/house-process.js'
import { DEFAULT_SLEEP, DEFAULT_SLOTS } from './lib/slots.js'
import { QQ } from './qq.js'
import {
  TIME_UP_TEXT, buildNudge, endAsk, buildWakeMessage, checkSlots, dayOf, findSlot, formatDuration, hhmm, localDay, localIso, parseClock, planBed, planDay,
  recapEvents,
} from './lib/wake.js'

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url))
const DEFAULT_HOUSE_DIR = resolve(PLUGIN_DIR, '..', 'house')
const DEFAULT_STATE_DIR = join(homedir(), '.dsh', 'little-house')

export const name = 'little-house'

const MAX_LOG_BYTES = 1024 * 1024
const DO_CHUNK_SECONDS = 240 // one /do or /report request waits at most this long (Node's fetch gives up after 5 min)
const NUDGE_DELAY_MS = 2 * 60_000
const MIN_SLOT_MINUTES = 5
const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const MEMORY_DELAY_MINUTES = 10 // after the day changes, before the day is summarised
const MEMORY_TIMEOUT_MS = 10 * 60_000
const TRANSCRIPT_RESULT_CHARS = 400
const INTRO_RE = /^（\d{4}-\d{2}-\d{2} 周.，新的一天。）/

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
      })).default(DEFAULT_SLOTS).description('每天的自由活动时段：在 from–to 之间随机挑一个开始时间（每天投一次）。第一段开始时她醒来'),
      firstWakeDelaySeconds: Schema.natural().default(0).description('测试用：DSH 启动后过多少秒先来一次临时的自由活动（0 = 只按作息表）'),
      testMinutes: Schema.number().min(1).default(40).description('测试用的临时自由活动有多少分钟'),
      maxActionsPerWake: Schema.natural().default(40).description('每次自由活动最多调用多少次 house_do（安全上限；平时由时间约束）'),
      maxNudges: Schema.natural().default(2).description('她提前停下但时间还没到时，最多再叫她几次'),
    }).default({}),
    sleep: Schema.object({
      from: Schema.string().default(DEFAULT_SLEEP.from).description('最早几点睡觉 HH:MM'),
      to: Schema.string().default(DEFAULT_SLEEP.to).description('最晚几点睡觉 HH:MM（睡前会让她整理当天的日记；睡着以后手机静音，第一段自由活动开始时醒来）'),
    }).default({}),
    control: Schema.object({
      maxMinutes: Schema.number().min(1).default(30).description('自由活动以外，主人请她在屋里做事时，她最多接管角色多久'),
    }).default({}),
    session: Schema.object({
      agentPreset: Schema.string().default('little-house'),
      title: Schema.string().default('小屋生活'),
      rolloverHour: Schema.natural().max(23).default(0).description('几点换成新的一天：每天一个会话（小屋生活和手机 QQ 在同一个会话里），日记和记忆也按这个换天'),
    }).default({}),
    memory: Schema.object({
      enabled: Schema.boolean().default(true).description('每天换天后，用一个单独的会话（不带人设）把前一天的日记和 QQ 聊天整理进记忆'),
      preset: Schema.string().default('little-house-memory'),
    }).default({}),
    qq: Schema.object({
      enabled: Schema.boolean().default(false).description('接入 QQ（NapCat 的 OneBot 11 WebSocket 服务端）'),
      url: Schema.string().default('ws://127.0.0.1:3001').description('NapCat「WebSocket 服务端」的地址'),
      accessToken: Schema.string().default('').description('和 NapCat 里填的 token 一致'),
      ownerQQ: Schema.string().default('').description('主人的 QQ 号'),
      ownerName: Schema.string().default('主人').description('她怎么称呼主人'),
      others: Schema.union(['friends', 'listed', 'none']).default('friends').description('除了主人，还接受谁的私聊：friends = 她的 QQ 好友都可以；listed = 只有 friends 里列的；none = 只有主人'),
      friends: Schema.array(Schema.string()).default([]).description('others 为 listed 时，接受这些 QQ 号的私聊'),
      // Group chats are off for now (see qq.js):
      // groups: Schema.array(Schema.string()).default([]).description('她在哪些群里（群号）'),
      // names: Schema.array(Schema.string()).default(['小栖']).description('群里提到这些名字也算在叫她'),
      sleepReply: Schema.string().default('（睡着了……zzZ）').description('她睡着时收到消息自动回的话（消息不会交给她；同一个聊天半小时最多一次；留空 = 不回）'),
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
    this.qq = config.qq.enabled ? new QQ(this, config.qq) : undefined
    /** sessionId -> { texts, resolve, reject } for one-shot sessions (the memory summariser) */
    this.waiters = new Map()
    this.stateLock = Promise.resolve()
    this.memoryTimer = undefined
    this.bedTimer = undefined
    /** today's { day, wake, bed } (epoch ms), see dayTimes() */
    this.times = undefined
    /** sessionId -> { until, timer }: she took over her character outside free time */
    this.controls = new Map()

    ctx.effect(() => {
      const boot = setTimeout(() => {
        this.start().catch((e) => this.log('warn', `start failed: ${e?.stack ?? e}`))
      }, 0)
      return () => {
        clearTimeout(boot)
        clearTimeout(this.wakeTimer)
        clearTimeout(this.memoryTimer)
        clearTimeout(this.bedTimer)
        for (const c of this.controls.values()) clearTimeout(c.timer)
        for (const w of this.windows.values()) {
          clearTimeout(w.timer)
          clearTimeout(w.nudgeTimer)
        }
        this.qq?.stop()
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
      await this.house.request('POST', '/session', { free_until: 0, asleep: await this.isAsleep() })
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
    this.ctx.on('session/event', (session, event) => this.onSessionEvent(session, event))
    try {
      this.qq?.start()
    } catch (e) {
      this.log('warn', `QQ failed to start: ${e?.stack ?? e}`)
    }
    if (this.config.memory.enabled) this.scheduleMemory(30_000)
    if (!this.config.wake.enabled) return
    void this.scheduleBed()
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

  /** The whole persona (HTML comments in the file are notes for people, not for her). */
  async personaText() {
    const file = this.config.personaFile || join(PLUGIN_DIR, 'persona', 'default.md')
    try {
      return (await readFile(file, 'utf8')).replace(/<!--[\s\S]*?-->/g, '').trim()
    } catch (e) {
      this.log('warn', `persona file unreadable (${file}): ${e.message}`)
      return '你是住在一间海边小屋里的居民。'
    }
  }

  /** The persona's first paragraph: the short version that stays in the system prompt. */
  async personaBrief() {
    return (await this.personaText()).split(/\n\s*\n/)[0].trim()
  }

  // ------------------------------------------------------------------ sleep

  /** Today's wake-up (the first slot's start) and bedtime, rolled once a day. */
  async dayTimes(now = new Date()) {
    const day = localDay(now)
    if (this.times?.day === day) return this.times
    const first = this.slots[0]
    const plan = (await this.plans(now)).find((p) => p.name === first?.name && localDay(new Date(p.start)) === day)
    const wake = plan?.start ?? new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, first ? parseClock(first.from) : 450).getTime()
    let bed
    await this.updateState((s) => {
      bed = s.beds?.[day] ?? planBed(now, this.config.sleep)
      return { ...s, beds: { [day]: bed } }
    })
    this.times = { day, wake, bed }
    this.log('info', `today she wakes up at ${hhmm(wake)} and goes to bed at ${hhmm(bed)}`)
    return this.times
  }

  /** Asleep: from bedtime until the first free time of the next day. */
  async isAsleep(now = Date.now()) {
    const t = await this.dayTimes(new Date(now))
    return now < t.wake || now >= t.bed
  }

  async scheduleBed() {
    clearTimeout(this.bedTimer)
    const now = Date.now()
    const t = await this.dayTimes(new Date(now))
    if (now < t.bed) {
      this.bedTimer = setTimeout(() => {
        this.goToBed().catch((e) => this.log('warn', `bedtime failed: ${e?.stack ?? e}`)).finally(() => this.scheduleBed())
      }, t.bed - now)
      return
    }
    const tomorrow = new Date(now)
    tomorrow.setHours(24, 1, 0, 0)
    this.bedTimer = setTimeout(() => void this.scheduleBed(), tomorrow - now)
  }

  /** Bedtime: she goes to bed, may tidy up today's diary first; the phone is silent until morning. */
  async goToBed() {
    const state = await this.readState()
    const awakeToday = state.lifeSessionDay === this.dayKey() && state.lifeSessionId
    for (const sessionId of [...this.windows.keys()]) await this.endWindow(sessionId, 'bedtime')
    for (const sessionId of [...this.controls.keys()]) await this.endControl(sessionId, 'bedtime')
    await this.house.request('POST', '/session', { free_until: 0, asleep: true })
    this.log('info', 'bedtime')
    if (!awakeToday) return
    const agent = await this.dayAgent()
    await this.send(agent, `（${hhmm(Date.now())}，该睡觉了。你躺到了床上。）\n`
      + '睡前看看今天的日记（diary_read）：想补充的用 diary_write，想改或删掉的用 diary_edit。整理好就睡吧，不用再做别的事。'
      + '手机会静音到明天早上。')
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

  /** Read-modify-write the plugin state, one writer at a time. @param {(s: object) => object} fn */
  updateState(fn) {
    const run = this.stateLock.then(async () => this.writeState(await fn(await this.readState())))
    this.stateLock = run.catch(() => {})
    return run
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
      await this.updateState((s) => ({ ...s, plans: kept }))
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
      const agent = await this.dayAgent()
      const fresh = (await this.readState()).introducedSession !== agent.id

      // All times she is told come from the house's game clock (the same one the
      // picture and house_do results use), not from this process's clock.
      const skew = await this.clockSkew()
      for (const sessionId of [...this.controls.keys()]) await this.endControl(sessionId, 'free time', false)
      const session = await this.house.request('POST', '/session', { free_until: (until + skew) / 1000, asleep: false })
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
        recap: fresh && !(await this.memoryText()) ? recap : [], // in an ongoing session she has it already
        news: news.map((n) => n.text),
        look: look.text,
        resumed,
        wokeUp: plan.name === this.slots[0]?.name && localDay(new Date(plan.start)) === localDay(now),
      })
      await this.send(agent, text)
      await this.updateState((s) => ({ ...s, lastWakeAt: now.toISOString() }))
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
    await this.deliver(agent, [{ type: 'text', text }], 'little-house')
  }

  /**
   * Hand her a message in the day session. The first message of a session opens
   * with the date and her memory. `steer`: an idle session starts a turn; a busy
   * one (free time in progress, or answering the phone) reads it at its next step.
   */
  async deliver(agent, content, kind) {
    const intro = await this.intro(agent)
    const parts = intro ? [{ type: 'text', text: intro }, ...content] : content
    agent.steer(createUserMessage({ content: parts, source: { kind } }))
    await this.ctx.sessions.flush(agent.session)
    void agent.whenIdle().then(
      () => this.onIdle(agent),
      (e) => this.log('warn', `life turn ended with error: ${e}`),
    )
  }

  /** The opening of a day session (once per session): the date, then her memory. */
  async intro(agent) {
    let first = false
    await this.updateState((s) => {
      first = s.introducedSession !== agent.id
      return first ? { ...s, introducedSession: agent.id } : s
    })
    if (!first) return ''
    const day = this.dayKey()
    const lines = [`（${day} ${WEEKDAYS[new Date(day + 'T12:00').getDay()]}，新的一天。）`, '', '## 你是谁', await this.personaText()]
    const memory = await this.memoryText()
    if (memory) lines.push('', '## 你的记忆', '（你记得的事。越久的越模糊。）', memory)
    else {
      const note = await this.lastDiaryNote()
      if (note) lines.push('', `日记里最近的一段${note}`)
    }
    return lines.join('\n') + '\n\n---\n\n'
  }

  /** A QQ message arrived: the phone buzzes in her day session, whatever she is doing. */
  async phoneBuzz({ line, images = [] }) {
    const agent = await this.dayAgent()
    let head = '（手机响了，是 QQ 消息：）'
    if (!this.window(agent.id) && !this.controls.has(agent.id)) {
      // outside free time: tell her what her character is doing right now
      try {
        const s = await this.house.request('GET', '/status')
        const doing = s.idle ? `，${s.idle.replace(/^在/, '')}` : s.doing ? `，正在 ${s.doing}` : ''
        head = `（${hhmm(s.now * 1000)}，不是自由活动时间。你的角色此刻在${s.location_name}${doing}。手机响了，是 QQ 消息：）`
      } catch {
        head = `（${hhmm(Date.now())}，不是自由活动时间。手机响了，是 QQ 消息：）`
      }
    }
    await this.deliver(agent, [{ type: 'text', text: `${head}\n${line}` }, ...images], 'little-house-qq')
  }

  // ------------------------------------------------------------------ taking over outside free time

  /** Whether she has taken over her character right now (outside free time). */
  controlOpen(sessionId) {
    return this.controls.has(sessionId)
  }

  /** She takes over her character (the owner asked her to do something in the house). */
  async startControl(sessionId) {
    const until = Date.now() + this.config.control.maxMinutes * 60_000
    const skew = await this.clockSkew()
    await this.house.request('POST', '/session', { free_until: (until + skew) / 1000, asleep: false })
    const timer = setTimeout(() => void this.endControl(sessionId, 'time is up'), until - Date.now())
    this.controls.set(sessionId, { until, timer })
    this.budgets.set(sessionId, { actions: 0, max: this.config.wake.maxActionsPerWake })
    this.log('info', `she took over her character (session ${sessionId})`)
  }

  /** Back to the everyday routine (end_of_current_operation, end of her turn, or the time limit). */
  async endControl(sessionId, reason, release = true) {
    const c = this.controls.get(sessionId)
    if (!c) return false
    clearTimeout(c.timer)
    this.controls.delete(sessionId)
    if (release) {
      try {
        await this.house.request('POST', '/session', { free_until: 0 })
      } catch (e) {
        this.log('warn', `could not hand her back to the routine: ${e.message}`)
      }
    }
    this.log('info', `control over (session ${sessionId}): ${reason}`)
    return true
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
    if (!w || (w.ended && (w.rested || w.diary))) return undefined // written outside free time
    w.diary = true
    return w.name
  }

  /** end_free_time: the first time in a free time it asks (diary? a message?) instead of ending. */
  askBeforeEnd(sessionId) {
    const w = this.windows.get(sessionId)
    if (!w || w.asked) return ''
    w.asked = true
    return endAsk(Boolean(this.qq?.connected && this.config.qq.ownerQQ))
  }

  /** Free time ran out. If she is idle (and has not ended it herself), tell her. */
  async timeUp(sessionId) {
    const w = this.windows.get(sessionId)
    await this.endWindow(sessionId, 'time is up')
    if (!w || w.rested || w.agent?.status !== 'idle') return
    try {
      await this.send(w.agent, TIME_UP_TEXT)
      this.log('info', `asked for the diary at the end of ${w.name} (session ${sessionId})`)
    } catch (e) {
      this.log('warn', `could not ask for the diary: ${e?.message ?? e}`)
    }
  }

  /** Whether this session had free time that is now over (`unrested`: and she has not ended it herself). */
  windowOver(sessionId, unrested = false) {
    const w = this.windows.get(sessionId)
    return Boolean(w && w.ended && !(unrested && w.rested))
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
    await this.updateState((s) => ({ ...s, lastRestAt: new Date().toISOString(), doneSlots: [...(s.doneSlots ?? []), w.key].slice(-20) }))
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
    if (agent.status === 'idle' && this.controls.has(agent.id)) void this.endControl(agent.id, 'her turn ended')
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
    return lastEntryNote(join(this.stateDir, 'diary'), new Date(), this.dayKey())
  }

  /** The day (YYYY-MM-DD) a moment belongs to: days change at session.rolloverHour. */
  dayKey(at = new Date()) {
    return dayOf(at, this.config.session.rolloverHour)
  }

  /**
   * The live Agent of today's session (free time in the house and the phone
   * share it), creating it when the day has changed.
   */
  async dayAgent() {
    // one at a time: a wake and a QQ message at the same moment must not open two sessions
    this.dayAgentPending ??= this.openDayAgent().finally(() => { this.dayAgentPending = undefined })
    return this.dayAgentPending
  }

  async openDayAgent() {
    const today = this.dayKey()
    const state = await this.readState()
    const controller = this.ctx.get('sessionController')
    if (controller === undefined) throw new Error('sessionController is unavailable (is this the Web/Desktop profile?)')
    const resolveAgent = async (sessionId) => {
      const resolved = await controller.resolveAgent(sessionId)
      if ('error' in resolved) throw resolved.error
      return resolved.agent
    }
    if (state.lifeSessionId && state.lifeSessionDay === today) {
      try {
        const agent = await resolveAgent(state.lifeSessionId)
        this.daySession = { id: agent.id, day: today }
        return agent
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
    await this.updateState((s) => ({ ...s, lifeSessionId: agent.id, lifeSessionDay: today }))
    this.daySession = { id: agent.id, day: today }
    this.log('info', `created life session ${agent.id}`)
    return agent
  }

  // ------------------------------------------------------------------ memory (M4)

  get memoryPath() {
    return join(this.stateDir, 'memory', 'memory.json')
  }

  async readMemory() {
    try {
      return JSON.parse(await readFile(this.memoryPath, 'utf8'))
    } catch {
      return emptyMemory()
    }
  }

  /** Her memory as she reads it at the start of the day ('' when there is none yet). */
  async memoryText() {
    const mem = await this.readMemory()
    return mem.items.length || Object.keys(mem.people).length ? renderMemory(mem, this.dayKey()) : ''
  }

  /** Summarise every finished day not yet in memory, then again after the next day change. */
  scheduleMemory(delayMs) {
    clearTimeout(this.memoryTimer)
    this.memoryTimer = setTimeout(async () => {
      try {
        await this.catchUpMemory()
      } catch (e) {
        this.log('warn', `memory: ${e?.stack ?? e}`)
      }
      const now = new Date()
      const next = new Date(now.getFullYear(), now.getMonth(), now.getDate(), this.config.session.rolloverHour, MEMORY_DELAY_MINUTES)
      if (next <= now) next.setDate(next.getDate() + 1)
      this.scheduleMemory(next - now)
    }, delayMs)
  }

  /** Days (before today) with a diary or QQ chats that memory has not taken in. At most the last 7. */
  async pendingMemoryDays() {
    const mem = await this.readMemory()
    const today = this.dayKey()
    const days = new Set()
    for (const [sub, ext] of [['diary', '.md'], ['qq', '.jsonl'], ['transcripts', '.jsonl']]) {
      try {
        for (const f of await readdir(join(this.stateDir, sub))) {
          if (f.endsWith(ext)) days.add(f.slice(0, -ext.length))
        }
      } catch {
        // nothing there yet
      }
    }
    return [...days].filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d) && d < today && !mem.doneDays.includes(d)).sort().slice(-7)
  }

  async catchUpMemory() {
    for (const day of await this.pendingMemoryDays()) await this.summariseDay(day)
  }

  /** One day into memory: a fresh summarising session reads the day and answers in JSON. */
  /**
   * Keep the day session as plain lines (transcripts/<day>.jsonl) for the night's
   * memory summary: what she was told, what she wrote, every tool call and (cut
   * short) its result. Her reasoning and the day's opening (persona, memory) are left out.
   */
  async recordTranscript(day, event) {
    const d = event?.data ?? {}
    const text = (content) => (content ?? []).map((b) => (b.type === 'text' ? b.text : b.type === 'image' ? '[图片]' : '')).join('')
    let entry
    if (event.type === 'user/message') {
      const t = (d.content ?? []).filter((b) => !(b.type === 'text' && (INTRO_RE.test(b.text) || b.text.startsWith('<system-reminder>'))))
      const s = text(t).trim()
      if (s) entry = { who: 'in', text: s }
    } else if (event.type === 'assistant/message') {
      const s = text((d.message?.content ?? []).filter((b) => b.type === 'text')).trim()
      if (s) entry = { who: 'she', text: s }
    } else if (event.type === 'tool/call') {
      entry = { who: 'call', tool: d.name, text: String(d.arguments ?? '') }
    } else if (event.type === 'tool/result') {
      entry = { who: 'result', text: text(d.message?.content).slice(0, TRANSCRIPT_RESULT_CHARS) }
    }
    if (!entry) return
    try {
      await mkdir(join(this.stateDir, 'transcripts'), { recursive: true })
      await appendFile(join(this.stateDir, 'transcripts', `${day}.jsonl`), JSON.stringify({ t: hhmm(event.time ?? Date.now()), ...entry }) + '\n', 'utf8')
    } catch (e) {
      this.log('warn', `transcript: ${e?.message ?? e}`)
    }
  }

  async summariseDay(day) {
    const read = async (path) => readFile(path, 'utf8').catch(() => '')
    const lines = (src) => src.split('\n').filter(Boolean).map((l) => {
      try {
        return JSON.parse(l)
      } catch {
        return undefined
      }
    })
    const diary = (await read(join(this.stateDir, 'diary', `${day}.md`))).trim()
    const transcript = formatTranscript(lines(await read(join(this.stateDir, 'transcripts', `${day}.jsonl`))))
    // older days (before transcripts were kept) only have the QQ log
    const chats = transcript ? '' : formatChats(lines(await read(join(this.stateDir, 'qq', `${day}.jsonl`))), this.config.qq.ownerName)
    let mem = await this.readMemory()
    if (diary || transcript || chats) {
      const prompt = buildSummaryPrompt({
        name: '她', day, diary, transcript, chats, memoryText: renderMemory(mem, day, { ids: true }),
      })
      const reply = parseReply(await this.runOnce(this.config.memory.preset, `记忆整理 · ${day}`, prompt))
      const merged = mergeDay(mem, day, reply)
      mem = merged.mem
      await mkdir(join(this.stateDir, 'memory'), { recursive: true })
      if (merged.added.length) {
        await appendFile(join(this.stateDir, 'memory', 'archive.jsonl'), merged.added.map((i) => JSON.stringify(i)).join('\n') + '\n', 'utf8')
      }
      this.log('info', `memory: ${day} summarised (${merged.added.length} new)`)
    } else {
      mem = { ...mem, doneDays: [...mem.doneDays, day] }
    }
    mem = forget(mem, this.dayKey())
    await mkdir(join(this.stateDir, 'memory'), { recursive: true })
    const tmp = this.memoryPath + '.tmp'
    await writeFile(tmp, JSON.stringify(mem, null, 1), 'utf8')
    await rename(tmp, this.memoryPath)
    await writeFile(join(this.stateDir, 'memory', 'memory.md'), `# 她的记忆（${this.dayKey()}）\n\n${renderMemory(mem, this.dayKey())}\n`, 'utf8')
  }

  /**
   * Run one prompt in a new session of `preset` and return the text it answers
   * (the session stays in DSH's list, so it can be read afterwards).
   */
  async runOnce(preset, title, text) {
    const controller = this.ctx.get('sessionController')
    if (controller === undefined) throw new Error('sessionController is unavailable')
    const sessionId = `session-${randomUUID()}`
    const cwd = join(this.stateDir, 'workspace')
    await mkdir(cwd, { recursive: true })
    await controller.create({ sessionId, cwd, agentPreset: preset })
    const resolved = await controller.resolveAgent(sessionId)
    if ('error' in resolved) throw resolved.error
    const agent = resolved.agent
    try {
      this.ctx.get('sessionTitle')?.rename(agent.session, title)
    } catch {
      // a title is nice to have
    }
    const done = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.waiters.delete(agent.id)
        reject(new Error(`${title}: no answer in time`))
      }, MEMORY_TIMEOUT_MS)
      this.waiters.set(agent.id, { texts: [], resolve: (t) => { clearTimeout(timer); resolve(t) }, reject })
    })
    agent.followup(createUserMessage({ content: [{ type: 'text', text }], source: { kind: 'little-house-memory' } }))
    await this.ctx.sessions.flush(agent.session)
    return done
  }

  onSessionEvent(session, event) {
    if (session?.id && session.id === this.daySession?.id) void this.recordTranscript(this.daySession.day, event)
    const w = this.waiters.get(session?.id)
    if (!w) return
    if (event.type === 'assistant/message') {
      const t = (event.data?.message?.content ?? []).filter((b) => b.type === 'text').map((b) => b.text).join('')
      if (t) w.texts.push(t)
    } else if (event.type === 'turn/end') {
      this.waiters.delete(session.id)
      w.resolve(w.texts.join('\n'))
    }
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
  async doScript(script, signal, lookOnly = false) {
    const timeoutMs = (DO_CHUNK_SECONDS + 30) * 1000
    let r = await this.house.request('POST', '/do', { script, wait: DO_CHUNK_SECONDS, look_only: lookOnly }, { timeoutMs, signal })
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
