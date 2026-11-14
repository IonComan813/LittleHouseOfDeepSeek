// Development only: a stand-in for NapCat's OneBot 11 WebSocket server, so the
// QQ side can be tested without a real QQ account.
//
//   node tools/fake-napcat.mjs [--port 3001] [--control 3002] [--token T] [--log out.jsonl]
//
// The plugin dials ws://127.0.0.1:3001. Drive it over HTTP on the control port:
//   POST /private {"user_id": "123", "text": "在吗", "image": true, "voice": true, "nickname": "主人"}
//   POST /group   {"group_id": "456", "user_id": "789", "text": "...", "at": true, "card": "阿陆"}
//   GET  /outbox  -> everything the plugin sent (send_private_msg / send_group_msg)
//   GET  /img.png -> a test picture (what "image": true points at)
// Needs the `ws` package: DSH ships it (LH_DSH_MODULES, default /opt/lh/dsh/node_modules).

import { appendFileSync, readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { join } from 'node:path'

const require = createRequire(join(process.env.LH_DSH_MODULES || '/opt/lh/dsh/node_modules', 'x.js'))
const { WebSocketServer } = require('ws')

const arg = (name, def) => {
  const i = process.argv.indexOf(`--${name}`)
  return i > 0 ? process.argv[i + 1] : def
}
const PORT = Number(arg('port', 3001))
const CONTROL = Number(arg('control', 3002))
const TOKEN = arg('token', '')
const LOG = arg('log', '')
const IMAGE = arg('image', '')
const SELF = 10001

const outbox = []
let client
let msgId = 1000

function log(entry) {
  if (LOG) appendFileSync(LOG, JSON.stringify({ t: new Date().toISOString(), ...entry }) + '\n')
}

const wss = new WebSocketServer({ port: PORT, host: '127.0.0.1' })
wss.on('connection', (ws, req) => {
  const url = new URL(req.url, 'http://x')
  const token = url.searchParams.get('access_token') || (req.headers.authorization || '').replace(/^Bearer /, '')
  if (TOKEN && token !== TOKEN) {
    ws.close(1008, 'bad token')
    return
  }
  client = ws
  console.log('plugin connected')
  ws.send(JSON.stringify({ post_type: 'meta_event', meta_event_type: 'lifecycle', sub_type: 'connect', self_id: SELF, time: Date.now() / 1000 }))
  ws.on('message', (raw) => {
    const { action, params, echo } = JSON.parse(String(raw))
    let data = null
    if (action === 'get_login_info') data = { user_id: SELF, nickname: '小栖' }
    else if (action === 'get_group_info') data = { group_id: Number(params.group_id), group_name: '潮汐湾居民群' }
    else if (action === 'send_private_msg' || action === 'send_group_msg') {
      data = { message_id: ++msgId }
      const shown = params.message.map((s) => s.type === 'text' ? s.data.text
        : s.type === 'face' ? `<face ${s.data.id}>`
        : s.type === 'image' ? `<image ${String(s.data.file).slice(0, 20)}… ${String(s.data.file).length} chars>` : `<${s.type}>`).join('')
      const entry = { action, to: params.user_id ?? params.group_id, message_id: data.message_id, text: shown }
      outbox.push(entry)
      log({ dir: 'out', ...entry })
      console.log('OUT', JSON.stringify(entry))
    }
    ws.send(JSON.stringify({ status: 'ok', retcode: 0, data, echo }))
  })
})

function push(event) {
  if (!client) throw new Error('plugin not connected')
  client.send(JSON.stringify(event))
}

const png = () => IMAGE ? readFileSync(IMAGE) : Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64')

createServer((req, res) => {
  let body = ''
  req.on('data', (c) => { body += c })
  req.on('end', () => {
    try {
      if (req.method === 'GET' && req.url === '/outbox') {
        res.setHeader('content-type', 'application/json')
        res.end(JSON.stringify(outbox))
        return
      }
      if (req.method === 'GET' && req.url === '/img.png') {
        res.setHeader('content-type', 'image/png')
        res.end(png())
        return
      }
      const p = JSON.parse(body || '{}')
      const message = []
      if (p.at) message.push({ type: 'at', data: { qq: String(SELF) } })
      if (p.text) message.push({ type: 'text', data: { text: p.text } })
      if (p.face) message.push({ type: 'face', data: { id: String(p.face) } })
      if (p.image) message.push({ type: 'image', data: { file: 'img.png', url: `http://127.0.0.1:${CONTROL}/img.png` } })
      if (p.voice) message.push({ type: 'record', data: { file: 'voice.amr' } })
      const base = { post_type: 'message', time: Math.floor(Date.now() / 1000), self_id: SELF, message_id: ++msgId, message, raw_message: p.text ?? '', font: 0 }
      if (req.url === '/private') {
        push({ ...base, message_type: 'private', sub_type: 'friend', user_id: Number(p.user_id), sender: { user_id: Number(p.user_id), nickname: p.nickname ?? '主人' } })
      } else if (req.url === '/group') {
        push({ ...base, message_type: 'group', sub_type: 'normal', group_id: Number(p.group_id), user_id: Number(p.user_id), sender: { user_id: Number(p.user_id), nickname: p.card ?? '群友', card: p.card ?? '' } })
      } else {
        res.statusCode = 404
        res.end('?')
        return
      }
      log({ dir: 'in', url: req.url, ...p })
      res.end('ok')
    } catch (e) {
      res.statusCode = 500
      res.end(String(e?.message ?? e))
    }
  })
}).listen(CONTROL, '127.0.0.1', () => console.log(`fake NapCat: ws ${PORT}, control http ${CONTROL}`))
