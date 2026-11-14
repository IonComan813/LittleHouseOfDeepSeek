// A minimal WebSocket client (RFC 6455) on node:http, for one local connection
// to NapCat. Node's built-in WebSocket goes through the global fetch dispatcher,
// which a host may route through an HTTP proxy (even for 127.0.0.1); a plain
// socket does not. Text frames only (OneBot is JSON), ping/pong, close,
// fragmented messages. Same event shape as the browser API: open / message /
// close / error via addEventListener.

import { randomBytes, createHash } from 'node:crypto'
import { request as httpRequest } from 'node:http'
import { request as httpsRequest } from 'node:https'

const GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
const CONNECT_TIMEOUT_MS = 10_000

export class SimpleWebSocket {
  /** @param {string} url ws:// or wss:// @param {{ headers?: Record<string, string> }} [opts] */
  constructor(url, opts = {}) {
    this.listeners = { open: [], message: [], close: [], error: [] }
    this.socket = undefined
    this.closed = false
    this.buffer = Buffer.alloc(0)
    this.fragments = []
    const u = new URL(url)
    const key = randomBytes(16).toString('base64')
    const request = u.protocol === 'wss:' ? httpsRequest : httpRequest
    const req = request({
      host: u.hostname,
      port: u.port || (u.protocol === 'wss:' ? 443 : 80),
      path: u.pathname + u.search,
      agent: false, // never through a proxy agent
      headers: {
        Connection: 'Upgrade',
        Upgrade: 'websocket',
        'Sec-WebSocket-Version': '13',
        'Sec-WebSocket-Key': key,
        ...opts.headers,
      },
    })
    const timer = setTimeout(() => req.destroy(new Error('connect timed out')), CONNECT_TIMEOUT_MS)
    req.on('upgrade', (res, socket, head) => {
      clearTimeout(timer)
      const expected = createHash('sha1').update(key + GUID).digest('base64')
      if (res.headers['sec-websocket-accept'] !== expected) {
        socket.destroy()
        this.fail(new Error('bad handshake'))
        return
      }
      this.socket = socket
      socket.setNoDelay(true)
      socket.on('data', (d) => this.onData(d))
      socket.on('close', () => this.finish())
      socket.on('error', (e) => this.emit('error', e))
      if (head?.length) this.onData(head)
      this.emit('open', {})
    })
    req.on('response', (res) => {
      clearTimeout(timer)
      res.resume()
      this.fail(new Error(`HTTP ${res.statusCode} (not a WebSocket server, or a wrong token)`))
    })
    req.on('error', (e) => {
      clearTimeout(timer)
      this.fail(e)
    })
    req.end()
  }

  addEventListener(type, fn) {
    this.listeners[type]?.push(fn)
  }

  emit(type, ev) {
    for (const fn of this.listeners[type] ?? []) fn(ev)
  }

  fail(error) {
    this.emit('error', { error, message: error.message })
    this.finish()
  }

  finish() {
    if (this.closed) return
    this.closed = true
    this.emit('close', {})
  }

  send(text) {
    if (!this.socket || this.closed) throw new Error('WebSocket is not open')
    this.socket.write(frame(0x1, Buffer.from(String(text), 'utf8')))
  }

  close() {
    if (this.socket && !this.closed) {
      try {
        this.socket.write(frame(0x8, Buffer.alloc(0)))
      } catch {
        // already gone
      }
      this.socket.end()
      setTimeout(() => this.socket?.destroy(), 1000).unref?.()
    }
    this.finish()
  }

  onData(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk])
    for (;;) {
      const b = this.buffer
      if (b.length < 2) return
      const fin = (b[0] & 0x80) !== 0
      const op = b[0] & 0x0f
      const masked = (b[1] & 0x80) !== 0
      let len = b[1] & 0x7f
      let off = 2
      if (len === 126) {
        if (b.length < 4) return
        len = b.readUInt16BE(2)
        off = 4
      } else if (len === 127) {
        if (b.length < 10) return
        len = Number(b.readBigUInt64BE(2))
        off = 10
      }
      const maskOff = off
      if (masked) off += 4
      if (b.length < off + len) return
      let payload = b.subarray(off, off + len)
      if (masked) {
        const mask = b.subarray(maskOff, maskOff + 4)
        payload = Buffer.from(payload.map((x, i) => x ^ mask[i % 4]))
      }
      this.buffer = b.subarray(off + len)
      if (op === 0x8) {
        this.close()
        return
      }
      if (op === 0x9) {
        this.socket?.write(frame(0xa, payload))
        continue
      }
      if (op === 0xa) continue
      if (op === 0x1 || op === 0x2 || op === 0x0) {
        this.fragments.push(Buffer.from(payload))
        if (fin) {
          const data = Buffer.concat(this.fragments).toString('utf8')
          this.fragments = []
          this.emit('message', { data })
        }
      }
    }
  }
}

/** One masked client frame. */
function frame(op, payload) {
  const len = payload.length
  const head = len < 126 ? Buffer.from([0x80 | op, 0x80 | len])
    : len < 65536 ? Buffer.from([0x80 | op, 0x80 | 126, len >> 8, len & 0xff])
      : Buffer.concat([Buffer.from([0x80 | op, 0x80 | 127]), (() => {
        const b = Buffer.alloc(8)
        b.writeBigUInt64BE(BigInt(len))
        return b
      })()])
  const mask = randomBytes(4)
  const body = Buffer.alloc(len)
  for (let i = 0; i < len; i++) body[i] = payload[i] ^ mask[i % 4]
  return Buffer.concat([head, mask, body])
}
