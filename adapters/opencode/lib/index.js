/**
 * brethof-brain for OpenCode AND Kilo Code — one native plugin, two
 * platforms: Kilo's 2026 core is OpenCode-derived and exposes the identical
 * plugin Hooks interface, so this single dependency-free file serves both
 * (OpenCode: .opencode/plugins/ or config `plugin` array; Kilo:
 * .kilocode/plugin/ or ~/.config/kilo/plugin/).
 *
 * Source-verified 2026-08-23 (anomalyco/opencode @ HEAD):
 *   "chat.message"  — fires per user message; appended parts are PERSISTED
 *                     into session history (sessions.updatePart), and the
 *                     runtime's own machine-text convention is
 *                     `synthetic: true` — ours carry it too, so the
 *                     archiver (and any other consumer) can tell the
 *                     human's words from injected memory.
 *   event           — "session.idle" fires when a turn settles; the plugin
 *                     client's session.messages() returns the full
 *                     conversation for archiving.
 *
 * Contract mapping:
 *   chat.message -> POST /v1/hooks/session-start (once per session)
 *                 + POST /v1/hooks/prompt-submit (per user message)
 *                 -> one synthetic text part appended to the message
 *   session.idle -> POST /v1/hooks/stop (new turns since last archive)
 *
 * Every hook is fail-open: memory must never break a run. The API key comes
 * from ~/.brethof-brain/config.json or the environment — the same triple
 * every brethof-brain adapter documents.
 */
import { appendFileSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

const NAME = 'brethof-brain'

function fileConfig() {
  try {
    const home = process.env.BRETHOF_BRAIN_HOME || join(homedir(), '.brethof-brain')
    return JSON.parse(readFileSync(join(home, 'config.json'), 'utf8')) || {}
  } catch {
    return {}
  }
}

let _cfg
function config(options = {}) {
  if (_cfg) return _cfg
  const f = fileConfig()
  _cfg = {
    endpoint: (options.endpoint || process.env.BRETHOF_BRAIN_ENDPOINT
      || f.endpoint || 'http://127.0.0.1:8610').replace(/\/+$/, ''),
    apiKey: options.apiKey || process.env.BRETHOF_BRAIN_API_KEY || f.api_key || '',
    project: options.project || process.env.BRETHOF_BRAIN_PROJECT
      || f.default_project || 'global',
    unlockPassphrase: process.env.BRETHOF_BRAIN_UNLOCK_PASSPHRASE
      || f.unlock_passphrase || '',
    lockAfterMinutes: parseInt(process.env.BRETHOF_BRAIN_LOCK_AFTER_MINUTES
      || f.lock_after_minutes || 0, 10) || 0,
  }
  if (!_cfg.apiKey) {
    console.warn('brethof-brain: no API key (env or ~/.brethof-brain/'
      + 'config.json) — memory disabled for this session')
  }
  return _cfg
}


// A HOSTED memory locks itself after idle minutes (the customer's own
// policy) and answers 423 until the passphrase opens it again. The Python
// client has presented it automatically since 08-30; the JS adapters did
// not, so a hosted customer on this harness lost memory after the first
// idle stretch (found 2026-09-04 provisioning OpenClaw). Same contract:
// POST <endpoint>/unlock {passphrase, idle_seconds?}, unauthenticated —
// the passphrase IS the authentication — then the original call retried
// ONCE. Unset passphrase: a locked memory is reported, never opened.
async function unlock() {
  const { endpoint, unlockPassphrase, lockAfterMinutes } = config()
  if (!unlockPassphrase) return false
  const body = { passphrase: unlockPassphrase }
  if (lockAfterMinutes) body.idle_seconds = lockAfterMinutes * 60
  try {
    const res = await fetch(endpoint + '/unlock', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal: AbortSignal.timeout(90_000),
    })
    return res.ok
  } catch {
    return false
  }
}

async function call(path, body, timeoutMs, retried = false) {
  const { endpoint, apiKey } = config()
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(endpoint + path, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + apiKey,
                 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    })
    if (res.status === 423 && !retried && await unlock()) {
      return call(path, body, timeoutMs, true)
    }
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  } finally {
    clearTimeout(t)
  }
}

// Per-session bookkeeping: brief fetched once, archive index monotonic (the
// server UPSERTs on (session_id, index, text) — replays are idempotent),
// pending queue defers turns through transient outages.
const state = new Map()
function stateFor(sessionID) {
  let s = state.get(sessionID)
  if (!s) {
    s = { briefP: undefined, brief: '', index: 0, archived: 0, pending: [] }
    state.set(sessionID, s)
  }
  return s
}

function textOf(parts) {
  if (!Array.isArray(parts)) return ''
  return parts
    .filter(p => p && p.type === 'text' && typeof p.text === 'string' && !p.synthetic)
    .map(p => p.text).join('\n')
}

function syntheticPart(message, text) {
  // The runtime's own injected-text convention (see prompt.ts agent-part
  // hint): a persisted text part flagged synthetic. "prt"-prefixed id per
  // the PartID schema.
  return {
    id: 'prt_bb' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10),
    messageID: message.id,
    sessionID: message.sessionID,
    type: 'text',
    synthetic: true,
    text,
  }
}

// ── OpenCode 2 (2026-09-11, the @opencode/cli package): "V1 plugin
// implementations do not run in V2". V2 reads the default export's `id` and
// `setup(ctx)` and ignores server(); V1 and Kilo read server() and ignore
// setup() — one file serves all three. V2's hooks: `prompt` (each user
// message, before admission) and `context` (before every primary model
// call; system parts added there reach only that call, never history), and
// ctx.session.wait/context for the settled turn's messages to archive.
// BRETHOF_BRAIN_DEBUG_FILE (set by the rig) traces what fired.
function dbg(...a) {
  const f = process.env.BRETHOF_BRAIN_DEBUG_FILE
  if (!f) return
  try { appendFileSync(f, new Date().toISOString() + ' ' + a.map(x =>
    typeof x === 'string' ? x : JSON.stringify(x)).join(' ') + '\n') } catch {}
}

function textOfV2(content) {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content.filter(p => p && p.type === 'text' && typeof p.text === 'string' && !p.synthetic)
    .map(p => p.text).join('\n')
}

async function archiveV2(ctx, s, sessionID, project) {
  const got = await ctx.session.context({ sessionID })
  const msgs = Array.isArray(got) ? got : (got?.messages || got?.data || [])
  const turns = []
  for (let i = s.archived; i < msgs.length; i++) {
    const m = msgs[i]
    const role = m?.role || m?.info?.role
    const text = textOfV2(m?.content ?? m?.parts).trim()
    if (!text || (role !== 'user' && role !== 'assistant')) continue
    turns.push({ index: s.index++, line_type: role, text, embed: true })
  }
  s.archived = msgs.length
  dbg('v2 archive', sessionID, msgs.length, 'messages', turns.length, 'turns')
  if (!turns.length && !s.pending.length) return
  const batch = [...s.pending, ...turns]
  const env = await call('/v1/hooks/stop', { project, session_id: sessionID, turns: batch }, 20_000)
  s.pending = (env && (env.status ?? 'ok') === 'ok') ? [] : batch
}

export default {
  id: NAME,
  async setup(ctx) {
    const options = ctx?.options || {}
    const { apiKey, project } = config(options)
    dbg('v2 setup', !!apiKey)
    if (!apiKey) return
    await ctx.session.hook('prompt', async (ev) => {
      try {
        const sessionID = ev.sessionID || 'opencode'
        const s = stateFor(sessionID)
        if (s.briefP === undefined) {
          s.briefP = call('/v1/hooks/session-start', { project }, 12_000)
            .then(env => { s.brief = env?.injection || '' })
            .catch(() => {})
        }
        const prompt = String(ev.prompt?.text || '').trim()
        s.recall = ''
        if (prompt) {
          const env = await call('/v1/hooks/prompt-submit',
            { project, prompt, session_id: sessionID }, 12_000)
          s.recall = env?.injection || ''
        }
        dbg('v2 prompt', sessionID, prompt.length, 'chars, recall', s.recall.length)
        // archive once the turn has settled — never blocks the prompt
        void (async () => {
          try { await ctx.session.wait({ sessionID }); await archiveV2(ctx, s, sessionID, project) }
          catch (e) { dbg('v2 archive failed', String(e)) }
        })()
      } catch (e) { dbg('v2 prompt failed', String(e)) }
    })
    await ctx.session.hook('context', async (ev) => {
      try {
        const s = stateFor(ev.sessionID || 'opencode')
        await s.briefP
        const text = [s.brief, s.recall].filter(Boolean).join('\n\n')
        if (text) ev.system.push({ type: 'text', text })
        dbg('v2 context', ev.sessionID, text.length, 'chars injected')
      } catch (e) { dbg('v2 context failed', String(e)) }
    })
  },
  async server(input, options = {}) {
    const client = input.client
    return {
      // ── inject: brief once per session + ambient recall per message ───────
      async 'chat.message'(hookInput, output) {
        try {
          const { apiKey, project } = config(options)
          if (!apiKey) return
          const sessionID = hookInput.sessionID
            || output.message?.sessionID || 'opencode'
          const s = stateFor(sessionID)
          if (s.briefP === undefined) {
            s.briefP = call('/v1/hooks/session-start', { project }, 12_000)
              .then(env => { s.brief = env?.injection || '' })
              .catch(() => {})
          }
          await s.briefP
          const prompt = textOf(output.parts).trim()
          let recall = ''
          if (prompt) {
            const env = await call('/v1/hooks/prompt-submit',
              { project, prompt, session_id: sessionID }, 12_000)
            recall = env?.injection || ''
          }
          // The brief rides the FIRST message only — parts are persisted,
          // so unlike a request overlay it stays in history for the whole
          // session without re-appending.
          const text = [s.brief && !s.briefSent ? s.brief : '', recall]
            .filter(Boolean).join('\n\n')
          if (s.brief) s.briefSent = true
          if (text) output.parts.push(syntheticPart(output.message, text))
        } catch { /* fail-open */ }
      },

      // ── archive: on turn settle, ship new turns from the session store ────
      async event({ event }) {
        try {
          if (event?.type !== 'session.idle') return
          const { apiKey, project } = config(options)
          if (!apiKey) return
          const sessionID = event.properties?.sessionID
          if (!sessionID) return
          const s = stateFor(sessionID)
          const res = await client.session.messages({ path: { id: sessionID } })
          const msgs = res?.data || []
          const turns = []
          for (let i = s.archived; i < msgs.length; i++) {
            const m = msgs[i]
            const role = m?.info?.role
            const text = textOf(m?.parts).trim()
            if (!text || (role !== 'user' && role !== 'assistant')) continue
            turns.push({ index: s.index++, line_type: role, text, embed: true })
          }
          s.archived = msgs.length
          if (!turns.length && !s.pending.length) return
          const batch = [...s.pending, ...turns]
          const env = await call('/v1/hooks/stop',
            { project, session_id: sessionID, turns: batch }, 20_000)
          s.pending = (env && (env.status ?? 'ok') === 'ok') ? [] : batch
        } catch { /* fail-open */ }
      },
    }
  },
}
