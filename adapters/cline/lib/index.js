/**
 * brethof-brain for Cline — a NATIVE Cline SDK plugin (AgentPlugin).
 *
 * Why native and not .clinerules file hooks (source-verified 2026-08-23 on
 * cline main @ 4.1.x, apps/vscode/src/sdk/hooks-adapter.ts):
 *   (a) TaskStart / UserPromptSubmit file hooks are GATE-ONLY in the SDK
 *       bridge — their contextModification is dropped; only Pre/PostToolUse
 *       inject. A zero-tool Q&A turn could never receive memory that way.
 *   (b) TaskComplete's payload carries only the final outputText — no
 *       transcript path — so a file-hook archiver never sees the exchange
 *       it must archive.
 * The plugin surface has both channels, typed:
 *
 *   beforeModel -> POST /v1/hooks/session-start + /v1/hooks/prompt-submit
 *                  -> memory appended to the MODEL REQUEST only (an overlay;
 *                  the stored conversation is never mutated, so injections
 *                  can never leak into the archive or recurse into recall)
 *   afterRun    -> POST /v1/hooks/stop -> the run's new turns archived
 *
 * Every hook is fail-open: memory must never break a run. The API key comes
 * from ~/.brethof-brain/config.json or the environment — the same triple
 * every other adapter documents.
 */
import { appendFileSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export const name = 'brethof-brain'

// BRETHOF_BRAIN_DEBUG=<path> turns the fail-open silence into file truth —
// the client repo's oldest lesson (2026-07-06 audit): silent swallowing is
// the biggest risk in a fail-open adapter. Never logs content, only shapes.
const DEBUG = process.env.BRETHOF_BRAIN_DEBUG || ''
function dbg(line) {
  if (!DEBUG) return
  try { appendFileSync(DEBUG, `${new Date().toISOString()} ${line}\n`) } catch {}
}

function fileConfig() {
  try {
    const home = process.env.BRETHOF_BRAIN_HOME || join(homedir(), '.brethof-brain')
    return JSON.parse(readFileSync(join(home, 'config.json'), 'utf8')) || {}
  } catch {
    return {}
  }
}

let _cfg
function config() {
  if (_cfg) return _cfg
  const f = fileConfig()
  _cfg = {
    endpoint: (process.env.BRETHOF_BRAIN_ENDPOINT || f.endpoint
      || 'http://127.0.0.1:8610').replace(/\/+$/, ''),
    apiKey: process.env.BRETHOF_BRAIN_API_KEY || f.api_key || '',
    project: process.env.BRETHOF_BRAIN_PROJECT || f.default_project || 'global',
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

// Per-conversation bookkeeping: the brief is fetched once, recall re-fetched
// per NEW user prompt, and the archive index advances monotonically (the
// server UPSERTs on (session_id, index, text) — replays are idempotent).
// `pending` defers turns through a transient outage instead of dropping them.
const state = new Map()
function stateFor(conv) {
  let s = state.get(conv)
  if (!s) {
    s = { briefP: undefined, brief: '', lastPrompt: '', recall: '',
          index: 0, archived: 0, pending: [] }
    state.set(conv, s)
  }
  return s
}

const convOf = (snapshot) =>
  String(snapshot?.conversationId ?? snapshot?.runId ?? snapshot?.agentId ?? 'cline')

function textOf(parts) {
  if (!Array.isArray(parts)) return ''
  return parts.filter(p => p && p.type === 'text' && typeof p.text === 'string')
    .map(p => p.text).join('\n')
}

// The runtime appends other hooks' contextModification into the stored
// conversation as <hook_context> user messages — those are injected context,
// not the human. Our own overlay never enters the stored messages at all.
const isHookContext = (text) => text.startsWith('<hook_context>')

// Cline wraps what the human typed — <user_input mode="act"> in the 3.0.x
// CLI (seen live in the rig), <task>/<feedback>/<answer> in other flows —
// and appends machine-generated <environment_details> blocks (open files,
// file listings — routinely 10-50KB). The server must see the HUMAN's
// words: recall on a 16KB wrapped prompt returns nothing while the bare
// sentence hits (measured 2026-08-23) — the query drowns in listing noise.
// The same cleaning keeps the archive a conversation, not listing spam.
function humanText(text) {
  let t = text.replace(/<environment_details>[\s\S]*?<\/environment_details>/g, '')
  const inner = t.match(
    /<(task|feedback|answer|user_message|user_input)(?:\s[^>]*)?>([\s\S]*?)<\/\1>/)
  if (inner) t = inner[2]
  t = t.trim()
  return t || text.trim()
}

function lastUserText(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m?.role !== 'user') continue
    const text = textOf(m.content).trim()
    if (!text || isHookContext(text)) continue
    return humanText(text)
  }
  return ''
}

function overlayMessage(text) {
  return {
    id: crypto.randomUUID(),
    role: 'user',
    createdAt: Date.now(),
    content: [{ type: 'text', text }],
    metadata: { brethofBrain: 'memory-overlay' },
  }
}

export default {
  name,
  manifest: { capabilities: ['hooks'] },
  setup() { /* hooks only — nothing to register */ },
  hooks: {
    // ── inject: session brief once, ambient recall per new user prompt ──────
    async beforeModel(ctx) {
      try {
        const { apiKey, project } = config()
        if (!apiKey) return undefined
        const s = stateFor(convOf(ctx.snapshot))
        if (s.briefP === undefined) {
          s.briefP = call('/v1/hooks/session-start', { project }, 12_000)
            .then(env => { s.brief = env?.injection || ''
                           dbg(`session-start: status=${env?.status} brief=${s.brief.length}ch`) })
            .catch(e => { dbg(`session-start: THREW ${e?.message}`) })
        }
        await s.briefP
        const prompt = lastUserText(ctx.request.messages)
        dbg(`beforeModel: msgs=${ctx.request.messages.length} prompt=${prompt.length}ch `
          + `new=${prompt !== s.lastPrompt} head="${prompt.slice(0, 60)}"`)
        if (prompt && prompt !== s.lastPrompt) {
          s.lastPrompt = prompt
          s.recall = ''
          const env = await call('/v1/hooks/prompt-submit',
            { project, prompt, session_id: convOf(ctx.snapshot) }, 12_000)
          s.recall = env?.injection || ''
          dbg(`prompt-submit: status=${env?.status ?? 'NULL'} recall=${s.recall.length}ch`)
        }
        const text = [s.brief, s.recall].filter(Boolean).join('\n\n')
        if (!text) return undefined
        // Request-only overlay: beforeModel's returned messages replace the
        // REQUEST, not the conversation store — re-applied every model call
        // so the model keeps seeing memory for the whole tool loop.
        return { messages: [...ctx.request.messages, overlayMessage(text)] }
      } catch {
        return undefined /* fail-open */
      }
    },

    // ── archive: the run's new turns, whatever the run's outcome ────────────
    async afterRun(ctx) {
      try {
        const { apiKey, project } = config()
        if (!apiKey) return
        const conv = convOf(ctx.snapshot)
        const s = stateFor(conv)
        const msgs = ctx.snapshot.messages || []
        const turns = []
        for (let i = s.archived; i < msgs.length; i++) {
          const m = msgs[i]
          const text = textOf(m?.content).trim()
          if (!text) continue
          if (m.role === 'user' && !isHookContext(text)) {
            turns.push({ index: s.index++, line_type: 'user',
                         text: humanText(text), embed: true })
          } else if (m.role === 'assistant') {
            turns.push({ index: s.index++, line_type: 'assistant', text, embed: true })
          }
        }
        s.archived = msgs.length
        if (!turns.length && !s.pending.length) return
        const batch = [...s.pending, ...turns]
        const env = await call('/v1/hooks/stop',
          { project, session_id: conv, turns: batch }, 20_000)
        s.pending = (env && (env.status ?? 'ok') === 'ok') ? [] : batch
      } catch { /* fail-open */ }
    },
  },
}
