// Starts, finds and talks to the Python house process.
//
// The house writes `<stateDir>/house.json` ({ port, token, pid }) when it is
// listening. If a healthy house is already running (for example one the user
// started by hand to watch the window), we attach to it instead of spawning.

import { spawn } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

const REQUEST_TIMEOUT_MS = 10_000

export class HouseUnavailableError extends Error {}

export class HouseProcess {
  /**
   * @param {{ python: string, houseDir: string, stateDir: string, port: number,
   *           autoStart: boolean, log: (level: string, msg: string) => void }} options
   */
  constructor(options) {
    this.options = options
    /** @type {import('node:child_process').ChildProcess | undefined} */
    this.child = undefined
    /** @type {{ port: number, token: string, pid: number } | undefined} */
    this.endpoint = undefined
    this.starting = undefined
    this.disposed = false
    this.restartDelayMs = 2_000
    this.restartTimer = undefined
  }

  get discoveryPath() {
    return join(this.options.stateDir, 'house.json')
  }

  async readDiscovery() {
    try {
      const data = JSON.parse(await readFile(this.discoveryPath, 'utf8'))
      if (typeof data.port === 'number' && typeof data.token === 'string') return data
    } catch {
      // missing or half-written: treat as not running
    }
    return undefined
  }

  async healthy(endpoint) {
    try {
      const res = await fetch(`http://127.0.0.1:${endpoint.port}/health`, { signal: AbortSignal.timeout(2_000) })
      return res.ok && (await res.json()).ok === true
    } catch {
      return false
    }
  }

  /** Ensure a house is reachable; spawn one when allowed. */
  async ensure() {
    if (this.disposed) throw new HouseUnavailableError('house manager is disposed')
    if (this.endpoint && await this.healthy(this.endpoint)) return this.endpoint
    const found = await this.readDiscovery()
    if (found && await this.healthy(found)) {
      this.endpoint = found
      return found
    }
    if (!this.options.autoStart) throw new HouseUnavailableError('小屋没有在运行（autoStart 已关闭）')
    this.starting ??= this.spawnAndWait().finally(() => { this.starting = undefined })
    return this.starting
  }

  async spawnAndWait() {
    const { python, houseDir, stateDir, port, log } = this.options
    const args = ['-m', 'littlehouse', '--state-dir', stateDir, '--port', String(port)]
    log('info', `starting house: ${python} ${args.join(' ')} (cwd ${houseDir})`)
    const child = spawn(python, args, {
      cwd: houseDir,
      env: { ...process.env, PYTHONPATH: houseDir, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })
    this.child = child
    child.stdout?.on('data', (b) => log('debug', `[house] ${String(b).trimEnd()}`))
    child.stderr?.on('data', (b) => log('warn', `[house] ${String(b).trimEnd()}`))
    const exited = new Promise((resolve) => child.once('exit', (code) => resolve(code)))
    child.once('error', (err) => log('warn', `house process error: ${err.message}`))
    child.once('exit', (code, signal) => {
      if (this.child === child) this.child = undefined
      this.endpoint = undefined
      if (this.disposed) return
      log('warn', `house exited (code ${code}, signal ${signal}); restarting in ${this.restartDelayMs / 1000}s`)
      clearTimeout(this.restartTimer)
      this.restartTimer = setTimeout(() => { this.ensure().catch((e) => log('warn', `house restart failed: ${e.message}`)) }, this.restartDelayMs)
      this.restartDelayMs = Math.min(this.restartDelayMs * 2, 60_000)
    })

    const deadline = Date.now() + 15_000
    while (Date.now() < deadline) {
      const result = await Promise.race([exited.then(() => 'exited'), sleep(300).then(() => 'tick')])
      if (result === 'exited') throw new HouseUnavailableError('小屋进程启动后立刻退出了，请检查 python 路径和日志')
      const found = await this.readDiscovery()
      if (found && found.pid === child.pid && await this.healthy(found)) {
        this.endpoint = found
        this.restartDelayMs = 2_000
        return found
      }
    }
    child.kill()
    throw new HouseUnavailableError('小屋进程 15 秒内没有就绪')
  }

  /**
   * Call the house API.
   * @param {'GET' | 'POST'} method
   * @param {string} path
   * @param {unknown} [body]
   * @param {{ timeoutMs?: number, signal?: AbortSignal }} [options]
   */
  async request(method, path, body, options = {}) {
    const ep = await this.ensure()
    const timeout = AbortSignal.timeout(options.timeoutMs ?? REQUEST_TIMEOUT_MS)
    const res = await fetch(`http://127.0.0.1:${ep.port}${path}`, {
      method,
      headers: { 'X-House-Token': ep.token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: options.signal ? AbortSignal.any([timeout, options.signal]) : timeout,
    })
    const data = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }))
    if (res.status === 401) this.endpoint = undefined // token rotated by a restart: rediscover next time
    if (!res.ok) throw new HouseUnavailableError(data.error ?? `HTTP ${res.status}`)
    return data
  }

  /**
   * GET a binary resource (the PNG screenshot).
   * @param {string} path
   * @returns {Promise<Uint8Array>}
   */
  async requestBytes(path) {
    const ep = await this.ensure()
    const res = await fetch(`http://127.0.0.1:${ep.port}${path}`, {
      headers: { 'X-House-Token': ep.token },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS * 3),
    })
    if (res.status === 401) this.endpoint = undefined
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new HouseUnavailableError(data.error ?? `HTTP ${res.status}`)
    }
    return new Uint8Array(await res.arrayBuffer())
  }

  async dispose() {
    this.disposed = true
    clearTimeout(this.restartTimer)
    const child = this.child
    if (!child) return
    // Ask politely first so the world is saved, then make sure it is gone.
    try {
      if (this.endpoint) {
        await fetch(`http://127.0.0.1:${this.endpoint.port}/shutdown`, {
          method: 'POST',
          headers: { 'X-House-Token': this.endpoint.token, 'Content-Type': 'application/json' },
          body: '{}',
          signal: AbortSignal.timeout(2_000),
        })
      }
    } catch {
      // fall through to kill
    }
    const gone = new Promise((resolve) => child.once('exit', resolve))
    if (await Promise.race([gone.then(() => true), sleep(3_000).then(() => false)])) return
    child.kill()
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
