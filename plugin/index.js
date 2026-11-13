// dsh-little-house — host-level plugin.
//
// Provides the `littleHouse` service: it keeps the Python house process alive,
// wakes the resident at random times into a dedicated "life" session (which
// runs the `little-house` agent preset), and hands the agent-scoped tools in
// ./agent-scope.js their house client and per-wake budget.

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
import {
  buildWakeMessage, formatDuration, recapEvents, inQuietHours, localDay, localIso, msUntilQuietEnds, parseQuietHours, randomDelayMs,
} from './lib/wake.js'

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url))
const DEFAULT_HOUSE_DIR = resolve(PLUGIN_DIR, '..', 'house')
const DEFAULT_STATE_DIR = join(homedir(), '.dsh', 'little-house')

export const name = 'little-house'

const MAX_LOG_BYTES = 1024 * 1024

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
      minIntervalMinutes: Schema.number().min(1).default(90),
      maxIntervalMinutes: Schema.number().min(1).default(240),
      quietHours: Schema.string().default('00:30-08:00').description('这段时间不随机唤醒，格式 HH:MM-HH:MM'),
      maxPerDay: Schema.natural().default(8),
      firstWakeDelaySeconds: Schema.natural().default(120).description('DSH 启动后第一次唤醒前等待的秒数'),
      maxActionsPerWake: Schema.natural().default(12).description('每次醒来最多调用多少次 house_do'),
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
    this.quiet = parseQuietHours(config.wake.quietHours)
    this.wakeTimer = undefined
    this.waking = false
    /** Per-session budget for the current wake: sessionId -> { actions, max } */
    this.budgets = new Map()

    ctx.effect(() => {
      const boot = setTimeout(() => {
        this.start().catch((e) => this.log('warn', `start failed: ${e?.stack ?? e}`))
      }, 0)
      return () => {
        clearTimeout(boot)
        clearTimeout(this.wakeTimer)
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
    if (this.config.wake.enabled) this.schedule(this.config.wake.firstWakeDelaySeconds * 1000)
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

  // ------------------------------------------------------------------ wake loop

  schedule(delayMs) {
    clearTimeout(this.wakeTimer)
    const next = new Date(Date.now() + delayMs)
    this.log('info', `next wake at ${next.toLocaleString()}`)
    this.wakeTimer = setTimeout(() => {
      this.wake('random')
        .catch((e) => this.log('warn', `wake failed: ${e?.stack ?? e}`))
        .finally(() => this.schedule(randomDelayMs(this.config.wake.minIntervalMinutes, this.config.wake.maxIntervalMinutes)))
    }, delayMs)
  }

  /**
   * Wake the resident once. Returns a short status string.
   * @param {'random' | 'manual'} reason
   */
  async wake(reason) {
    if (this.waking) return 'busy: a wake is already being delivered'
    this.waking = true
    try {
      const now = new Date()
      if (reason === 'random' && inQuietHours(now, this.quiet)) {
        const wait = msUntilQuietEnds(now, this.quiet)
        this.log('info', `quiet hours, skipping (ends in ${formatDuration(wait)})`)
        return 'skipped: quiet hours'
      }
      const state = await this.readState()
      const today = localDay(now)
      const count = state.wakeDay === today ? (state.wakeCount ?? 0) : 0
      if (reason === 'random' && count >= this.config.wake.maxPerDay) {
        this.log('info', `daily wake limit reached (${count})`)
        return 'skipped: daily limit'
      }

      const look = await this.house.request('GET', '/look')
      const agent = await this.lifeAgent(state, today)
      if (agent.status !== 'idle') {
        this.log('info', `life session ${agent.id} is busy (${agent.status}); not waking`)
        return 'skipped: agent busy'
      }

      const last = state.lastWakeAt ? new Date(state.lastWakeAt) : undefined
      let news = []
      let recap = []
      if (last) {
        const since = encodeURIComponent(localIso(last))
        try {
          news = (await this.house.request('GET', `/news?since=${since}`)).news ?? []
          recap = recapEvents((await this.house.request('GET', `/events?since=${since}&actor=resident`)).events ?? [])
        } catch (e) {
          this.log('warn', `could not read house news: ${e.message}`)
        }
      }
      this.budgets.set(agent.id, { actions: 0, max: this.config.wake.maxActionsPerWake })
      const text = buildWakeMessage({
        sinceText: last ? formatDuration(now.getTime() - last.getTime()) : undefined,
        recap,
        news: news.map((n) => n.text),
        lastNote: await this.lastDiaryNote(),
        look: look.text,
        maxActions: this.config.wake.maxActionsPerWake,
      })
      agent.followup(createUserMessage({ content: [{ type: 'text', text }], source: { kind: 'little-house' } }))
      await this.ctx.sessions.flush(agent.session)

      await this.writeState({ ...state, wakeDay: today, wakeCount: count + 1, lastWakeAt: now.toISOString() })
      this.log('info', `woke the resident (${reason}) in session ${agent.id}`)
      void agent.whenIdle().then(
        () => this.log('info', `resident went back to rest (session ${agent.id})`),
        (e) => this.log('warn', `life turn ended with error: ${e}`),
      )
      return `woke: ${agent.id}`
    } finally {
      this.waking = false
    }
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
    state.lifeSessionId = agent.id
    state.lifeSessionDay = today
    await this.writeState(state)
    this.log('info', `created life session ${agent.id}`)
    return agent
  }

  // ------------------------------------------------------------------ tool support

  /** Count one house_do call against the current wake's budget. */
  takeAction(sessionId) {
    const b = this.budgets.get(sessionId)
    if (!b) return { ok: true, left: Infinity }
    if (b.actions >= b.max) return { ok: false, left: 0 }
    b.actions += 1
    return { ok: true, left: b.max - b.actions }
  }
}
