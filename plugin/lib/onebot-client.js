// A OneBot 11 client over a forward WebSocket: we dial NapCat's WebSocket
// server (NapCat: 网络配置 → WebSocket 服务端). Reconnects with backoff,
// matches action responses by `echo`.

import { SimpleWebSocket } from './ws-client.js'

const ACTION_TIMEOUT_MS = 20_000

export class OneBotClient {
  /**
   * @param {{ url: string, token?: string, log: (level: string, msg: string) => void,
   *           onEvent: (event: any) => void, onConnect?: () => void }} opts
   */
  constructor(opts) {
    this.opts = opts
    this.ws = undefined
    this.pending = new Map()
    this.seq = 0
    this.backoff = 2000
    this.timer = undefined
    this.stopped = false
    this.connected = false
    this.selfId = ''
  }

  start() {
    this.stopped = false
    this.connect()
  }

  stop() {
    this.stopped = true
    clearTimeout(this.timer)
    try {
      this.ws?.close()
    } catch {
      // already closed
    }
    for (const p of this.pending.values()) p.reject(new Error('OneBot client stopped'))
    this.pending.clear()
  }

  connect() {
    if (this.stopped) return
    const { url, token } = this.opts
    let target = url
    if (token) target += (url.includes('?') ? '&' : '?') + 'access_token=' + encodeURIComponent(token)
    let ws
    try {
      ws = new SimpleWebSocket(target, token ? { headers: { Authorization: `Bearer ${token}` } } : {})
    } catch (e) {
      this.opts.log('warn', `QQ: cannot connect to ${url}: ${e?.message ?? e}`)
      this.retry()
      return
    }
    this.ws = ws
    ws.addEventListener('open', () => {
      this.connected = true
      this.backoff = 2000
      this.opts.log('info', `QQ: connected to ${url}`)
      this.call('get_login_info', {}).then(
        (info) => {
          if (info?.user_id) this.selfId = String(info.user_id)
          this.opts.onConnect?.()
        },
        (e) => this.opts.log('warn', `QQ: get_login_info failed: ${e.message}`),
      )
    })
    ws.addEventListener('message', (ev) => {
      let data
      try {
        data = JSON.parse(String(ev.data))
      } catch {
        return
      }
      if (data && data.echo !== undefined && this.pending.has(data.echo)) {
        const p = this.pending.get(data.echo)
        this.pending.delete(data.echo)
        clearTimeout(p.timer)
        if (data.status === 'ok' || data.retcode === 0) p.resolve(data.data)
        else p.reject(new Error(`${data.status ?? 'failed'} (retcode ${data.retcode}): ${data.message ?? data.wording ?? ''}`))
        return
      }
      if (data?.post_type) {
        if (data.self_id && !this.selfId) this.selfId = String(data.self_id)
        try {
          this.opts.onEvent(data)
        } catch (e) {
          this.opts.log('warn', `QQ: event handler failed: ${e?.stack ?? e}`)
        }
      }
    })
    ws.addEventListener('close', () => {
      const was = this.connected
      this.connected = false
      if (was) this.opts.log('warn', 'QQ: disconnected')
      for (const p of this.pending.values()) p.reject(new Error('OneBot disconnected'))
      this.pending.clear()
      this.retry()
    })
    ws.addEventListener('error', (ev) => {
      // 'close' follows and schedules the reconnect
      if (this.backoff <= 4000) this.opts.log('debug', `QQ: ${ev?.message ?? 'connection error'}`)
    })
  }

  retry() {
    if (this.stopped) return
    clearTimeout(this.timer)
    this.timer = setTimeout(() => this.connect(), this.backoff)
    this.backoff = Math.min(this.backoff * 2, 60_000)
  }

  /** Call a OneBot action. @param {string} action @param {object} params */
  call(action, params) {
    if (!this.ws || !this.connected) return Promise.reject(new Error('QQ is not connected'))
    const echo = `lh-${++this.seq}`
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(echo)
        reject(new Error(`${action} timed out`))
      }, ACTION_TIMEOUT_MS)
      this.pending.set(echo, { resolve, reject, timer })
      this.ws.send(JSON.stringify({ action, params, echo }))
    })
  }
}
