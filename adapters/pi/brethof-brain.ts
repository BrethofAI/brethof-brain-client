/**
 * brethof-brain for Pi (earendil-works/pi) — an in-process extension, so it
 * runs the same on Linux, macOS and Windows with no shell.
 *
 * Install: copy this file to ~/.pi/agent/extensions/brethof-brain.ts (on
 * Windows %USERPROFILE%\\.pi\\agent\\extensions\\), or `pi -e <path>`.
 * Key and endpoint from ~/.brethof-brain/config.json or the environment
 * (BRETHOF_BRAIN_API_KEY / _ENDPOINT / _PROJECT / _UNLOCK_PASSPHRASE).
 *
 *   session brief  — a system-prompt section, fetched once per session
 *   ambient recall — a hidden message before each prompt (before_agent_start)
 *   archive        — the run's user and assistant messages at agent_end
 *
 * Fail-open: a memory that cannot be reached never blocks Pi. Written
 * 2026-10-03 against Pi 1.0.1 (src/core/extensions/types.ts).
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
  return content.filter((p: any) => p && p.type === 'text' && typeof p.text === 'string')
    .map((p: any) => p.text).join('\n')
}

export default function brethofBrain(pi: any) {
  const state = new Map<string, any>()
  const stateFor = (sid: string) => {
    let s = state.get(sid)
    if (!s) { s = { brief: '', briefP: undefined, index: 0, pending: [] }; state.set(sid, s) }
    return s
  }
  const sidOf = (ctx: any) => String(ctx?.sessionManager?.getSessionId?.() ?? 'pi')

  pi.on('session_start', async (_event: any, ctx: any) => {
    try {
      const { apiKey, project } = config()
      if (!apiKey) return
      const s = stateFor(sidOf(ctx))
      if (s.briefP === undefined) {
        s.briefP = call('/v1/hooks/session-start', { project }, 12_000)
          .then((env: any) => { s.brief = env?.injection || '' }).catch(() => {})
      }
    } catch (e) { dbg('pi session_start failed', String(e)) }
  })

  pi.on('before_agent_start', async (event: any, ctx: any) => {
    try {
      const { apiKey, project } = config()
      if (!apiKey) return
      const sid = sidOf(ctx)
      const s = stateFor(sid)
      if (s.briefP === undefined) {
        s.briefP = call('/v1/hooks/session-start', { project }, 12_000)
          .then((env: any) => { s.brief = env?.injection || '' }).catch(() => {})
      }
      await s.briefP
      if (s.brief && event?.systemPromptOptions?.sections) {
        event.systemPromptOptions.sections.brethof_brain = s.brief
      }
      const prompt = String(event?.prompt ?? '').trim()
      let recall = ''
      if (prompt) {
        const env: any = await call('/v1/hooks/prompt-submit', { project, prompt, session_id: sid }, 12_000)
        recall = env?.injection || ''
      }
      dbg('pi before_agent_start', sid, 'brief', s.brief.length, 'recall', recall.length)
      if (recall) return { message: { customType: NAME, content: recall, display: false } }
    } catch (e) { dbg('pi before_agent_start failed', String(e)) }
  })

  pi.on('agent_end', async (event: any, ctx: any) => {
    try {
      const { apiKey, project } = config()
      if (!apiKey) return
      const sid = sidOf(ctx)
      const s = stateFor(sid)
      const turns: any[] = []
      for (const m of (Array.isArray(event?.messages) ? event.messages : [])) {
        const role = m?.role
        if (role !== 'user' && role !== 'assistant') continue
        const text = textOf(m?.content).trim()
        if (text) turns.push({ index: s.index++, line_type: role, text, embed: true })
      }
      dbg('pi agent_end', sid, turns.length, 'turns')
      if (!turns.length && !s.pending.length) return
      const batch = [...s.pending, ...turns]
      const env: any = await call('/v1/hooks/stop', { project, session_id: sid, turns: batch }, 20_000)
      s.pending = (env && (env.status ?? 'ok') === 'ok') ? [] : batch
    } catch (e) { dbg('pi agent_end failed', String(e)) }
  })
}
