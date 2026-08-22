/**
 * brethof-brain for DeepSeek Harness (dsh) — a NATIVE cordis plugin.
 *
 * Why native and not the CC hooks bridge: the bridge fires our hooks fine,
 * but (a) dsh's shell executor scrubs *_API_KEY from hook process envs, and
 * (b) at Stop time the persisted transcript deliberately omits the open
 * turn, so a bridge-based archiver can never see the exchange it is meant
 * to archive (both measured 2026-08-22). dsh's own design notes say it
 * plainly: anything bespoke should be a plugin on the typed extension
 * points. So: three listeners, full contract.
 *
 *   agent/session-start  -> POST /v1/hooks/session-start -> agent.inject()
 *   agent/pre-step       -> POST /v1/hooks/prompt-submit -> context message
 *   agent/turn-stopping  -> POST /v1/hooks/stop          -> turn archived
 *
 * Every listener is fail-open: memory must never break a run. The API key
 * comes from ~/.brethof-brain/config.json (or config/env) — the config FILE
 * is the reliable path under dsh, exactly because of the credential scrub.
 */
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export const name = 'brethof-brain'

const SOURCE = { kind: 'plugin', plugin: 'brethof-brain' }

// Inline twin of @deepseek-ai/dsh-llm's createUserMessage (frozen
// {content, source, role, id}) — importing the package from a
// profile-installed plugin is not reliably resolvable, and the runtime
// shape is this simple. MessageId is a branded string; a UUID satisfies it.
function createUserMessage(input) {
  return Object.freeze({ ...input, role: 'user', id: crypto.randomUUID() })
}

function fileConfig() {
  try {
    const home = process.env.BRETHOF_BRAIN_HOME || join(homedir(), '.brethof-brain')
    return JSON.parse(readFileSync(join(home, 'config.json'), 'utf8')) || {}
  } catch {
    return {}
  }
}

function textOf(blocks) {
  if (!Array.isArray(blocks)) return ''
  return blocks.filter(b => b && b.type === 'text').map(b => b.text).join('\n')
}

export function apply(ctx, config = {}) {
  const f = fileConfig()
  const endpoint = (config.endpoint || process.env.BRETHOF_BRAIN_ENDPOINT
    || f.endpoint || 'https://api.brethof.cloud').replace(/\/+$/, '')
  const apiKey = config.apiKey || process.env.BRETHOF_BRAIN_API_KEY || f.api_key || ''
  const project = config.project || process.env.BRETHOF_BRAIN_PROJECT
    || f.default_project || 'global'
  if (!apiKey) {
    ctx.logger?.warn?.('brethof-brain: no API key (config, env, or '
      + '~/.brethof-brain/config.json) — memory disabled for this run')
    return
  }

  // Per-agent archive bookkeeping: monotonically increasing index per
  // session (the server UPSERTs on (session_id, index, text) — replays are
  // idempotent), plus a pending queue so a transient outage defers turns
  // instead of dropping them.
  const state = new WeakMap()
  const forAgent = (agent) => {
    let s = state.get(agent)
    if (!s) { s = { index: 0, pending: [] }; state.set(agent, s) }
    return s
  }

  async function call(path, body, timeoutMs) {
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
      if (!res.ok) return null
      return await res.json()
    } catch {
      return null
    } finally {
      clearTimeout(t)
    }
  }

  const sessionIdOf = (agent) =>
    String(agent?.session?.id ?? agent?.session?.header?.id ?? 'dsh')

  // ── session start: brief the agent before turn 1 ─────────────────────────
  ctx.on('agent/session-start', async ({ agent }) => {
    try {
      const env = await call('/v1/hooks/session-start', { project }, 12_000)
      const block = env?.injection || ''
      if (block) {
        agent.inject(createUserMessage({
          content: [{ type: 'text', text: block }], source: SOURCE }))
      }
    } catch { /* fail-open */ }
  })

  // ── pre-step: ambient recall for the claimed user messages ───────────────
  ctx.on('agent/pre-step', async ({ agent, messages }, next) => {
    let extra = ''
    try {
      const prompt = (messages || [])
        .filter(m => m?.source?.kind === 'user')        // never recurse on our own context
        .map(m => textOf(m.content)).join('\n').trim()
      if (prompt) {
        const env = await call('/v1/hooks/prompt-submit',
          { project, prompt, session_id: sessionIdOf(agent) }, 12_000)
        extra = env?.injection || ''
      }
    } catch { /* fail-open */ }
    const decision = await next()
    if (extra && decision?.kind === 'enter') {
      return { kind: 'enter', messages: [...decision.messages, createUserMessage({
        content: [{ type: 'text', text: extra }], source: SOURCE })] }
    }
    return decision
  })

  // ── turn stop: archive the exchange (awaited — content is in the session) ─
  ctx.on('agent/turn-stopping', async ({ agent }) => {
    try {
      const s = forAgent(agent)
      const events = [...agent.session.events]
      // A user/message event's data IS the UserMessage — no turn field
      // (measured: filtering on data.turn dropped every user line). Track
      // the current turn positionally from turn/start markers instead.
      let last = -1
      for (const e of events) if (e.type === 'turn/start') last = e.data.turn
      const users = [], replies = []
      let cur = -1
      for (const e of events) {
        if (e.type === 'turn/start') cur = e.data.turn
        if (cur !== last) continue
        if (e.type === 'user/message' && e.data.source?.kind === 'user') {
          users.push(textOf(e.data.content))
        }
        if (e.type === 'assistant/message' && e.data.turn === last) {
          replies.push(textOf(e.data.message?.content))
        }
      }
      const turns = []
      const user = users.filter(Boolean).join('\n').trim()
      const reply = replies.filter(Boolean).join('\n').trim()
      if (user) turns.push({ index: s.index++, line_type: 'user', text: user, embed: true })
      if (reply) turns.push({ index: s.index++, line_type: 'assistant', text: reply, embed: true })
      if (!turns.length && !s.pending.length) return
      const batch = [...s.pending, ...turns]
      const env = await call('/v1/hooks/stop',
        { project, session_id: sessionIdOf(agent), turns: batch }, 20_000)
      s.pending = (env && (env.status ?? 'ok') === 'ok') ? [] : batch
    } catch { /* fail-open */ }
  })
}

export default { name, apply }
