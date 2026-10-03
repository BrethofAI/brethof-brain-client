/**
 * brethof-brain for Amp — a plugin, so it runs the same on Linux, macOS and
 * Windows with no shell (Amp runs plugins in its embedded Bun).
 *
 * Install: copy this file to ~/.config/amp/plugins/brethof-brain.ts (on
 * Windows %USERPROFILE%\\.config\\amp\\plugins\\). Plugins load by
 * themselves; in execute mode pass --plugin-ready-timeout so the turn waits
 * for them. Key and endpoint from ~/.brethof-brain/config.json or the
 * environment (BRETHOF_BRAIN_API_KEY / _ENDPOINT / _PROJECT / _UNLOCK_PASSPHRASE).
 *
 *   session brief  — with the first prompt of each thread (agent.start)
 *   ambient recall — appended to every prompt, hidden (agent.start)
 *   archive        — the prompt and the reply when the turn ends (agent.end)
 *
 * Amp's session.start cannot add text, so the brief rides the thread's
 * first prompt. Fail-open: a memory that cannot be reached never blocks
 * Amp. Written 2026-10-03 against Amp's plugin API (amp plugins show-docs).
 */
import { appendFileSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

const NAME = 'brethof-brain'

function dbg(...a: unknown[]) {
  const f = process.env.BRETHOF_BRAIN_DEBUG_FILE
  if (!f) return
  try { appendFileSync(f, new Date().toISOString() + ' ' + a.map(x =>
    typeof x === 'string' ? x : JSON.stringify(x)).join(' ') + '\n') } catch {}
}

function fileConfig(): any {
  try {
    const home = process.env.BRETHOF_BRAIN_HOME || join(homedir(), '.brethof-brain')
    return JSON.parse(readFileSync(join(home, 'config.json'), 'utf8')) || {}
  } catch {
    return {}
  }
}

let _cfg: any
function config(options: any = {}) {
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

async function call(path: string, body: any, timeoutMs: number, retried = false): Promise<any> {
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


function textOf(content: any): string {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content.filter((b: any) => b && b.type === 'text' && typeof b.text === 'string')
    .map((b: any) => b.text).join('\n')
}

export const description = 'brethof-brain — memory for your agents'

export default function (amp: any) {
  const state = new Map<string, any>()
  const stateFor = (tid: string) => {
    let s = state.get(tid)
    if (!s) { s = { briefed: false, index: 0, pending: [], prompt: '' }; state.set(tid, s) }
    return s
  }

  amp.on('agent.start', async (event: any) => {
    try {
      const { apiKey, project } = config()
      if (!apiKey) return {}
      const tid = String(event?.thread?.id ?? 'amp')
      const s = stateFor(tid)
      const prompt = String(event?.message ?? '').trim()
      s.prompt = prompt
      const parts: string[] = []
      if (!s.briefed) {
        s.briefed = true
        const env: any = await call('/v1/hooks/session-start', { project }, 12_000)
        if (env?.injection) parts.push(env.injection)
      }
      if (prompt) {
        const env: any = await call('/v1/hooks/prompt-submit', { project, prompt, session_id: tid }, 12_000)
        if (env?.injection) parts.push(env.injection)
      }
      dbg('amp agent.start', tid, 'parts', parts.map(p => p.length))
      return parts.length ? { message: { content: parts.join('\n\n'), display: false } } : {}
    } catch (e) { dbg('amp agent.start failed', String(e)); return {} }
  })

  amp.on('agent.end', async (event: any) => {
    try {
      const { apiKey, project } = config()
      if (!apiKey) return
      const tid = String(event?.thread?.id ?? 'amp')
      const s = stateFor(tid)
      // the user's own words — the thread's user message also carries our
      // appended memory block, which is not theirs to archive
      const prompt = String(event?.message ?? '').trim() || s.prompt
      const reply = (Array.isArray(event?.messages) ? event.messages : [])
        .filter((m: any) => m?.role === 'assistant').map((m: any) => textOf(m.content).trim())
        .filter(Boolean).join('\n\n')
      const turns: any[] = []
      if (prompt) turns.push({ index: s.index++, line_type: 'user', text: prompt, embed: true })
      if (reply) turns.push({ index: s.index++, line_type: 'assistant', text: reply, embed: true })
      dbg('amp agent.end', tid, event?.status, turns.length, 'turns')
      if (!turns.length && !s.pending.length) return
      const batch = [...s.pending, ...turns]
      const env: any = await call('/v1/hooks/stop', { project, session_id: tid, turns: batch }, 20_000)
      s.pending = (env && (env.status ?? 'ok') === 'ok') ? [] : batch
    } catch (e) { dbg('amp agent.end failed', String(e)) }
  })
}
