import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { createServer } from 'node:http'
import test from 'node:test'

import { SimpleWebSocket } from '../lib/ws-client.js'

/** A tiny echo server: answers the handshake, echoes text frames (unmasked), pings once. */
function server() {
  const srv = createServer()
  srv.on('upgrade', (req, socket) => {
    const accept = createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64')
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`)
    socket.write(Buffer.from([0x89, 0x00])) // ping
    let buf = Buffer.alloc(0)
    socket.on('data', (chunk) => {
      buf = Buffer.concat([buf, chunk])
      while (buf.length >= 2) { // every complete masked client frame
        let len = buf[1] & 0x7f
        let off = 2
        if (len === 126) { len = buf.readUInt16BE(2); off = 4 }
        if (buf.length < off + 4 + len) return
        const op = buf[0] & 0x0f
        const mask = buf.subarray(off, off + 4)
        const body = Buffer.from(buf.subarray(off + 4, off + 4 + len).map((x, i) => x ^ mask[i % 4]))
        buf = buf.subarray(off + 4 + len)
        if (op !== 0x1) continue // the pong
        const head = body.length < 126 ? Buffer.from([0x81, body.length]) : Buffer.from([0x81, 126, body.length >> 8, body.length & 0xff])
        socket.write(Buffer.concat([head, body]))
      }
    })
  })
  return new Promise((resolve) => srv.listen(0, '127.0.0.1', () => resolve(srv)))
}

test('SimpleWebSocket talks to a WebSocket server', async () => {
  const srv = await server()
  const ws = new SimpleWebSocket(`ws://127.0.0.1:${srv.address().port}/`)
  const got = []
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', () => {
      ws.send('你好')
      ws.send('x'.repeat(300))
    })
    ws.addEventListener('message', (ev) => {
      got.push(ev.data)
      if (got.length === 2) resolve()
    })
    ws.addEventListener('error', (ev) => reject(ev.error))
  })
  assert.deepEqual(got, ['你好', 'x'.repeat(300)])
  ws.close()
  srv.closeAllConnections()
  srv.close()
})

test('SimpleWebSocket reports a refused connection', async () => {
  const ws = new SimpleWebSocket('ws://127.0.0.1:1/')
  await new Promise((resolve) => ws.addEventListener('close', resolve))
})
