// Drive a JS adapter the way its platform does — one sitting: the session
// brief, one prompt's context, one archived exchange — with the endpoint and
// key from $BRETHOF_BRAIN_HOME/config.json (what `brethof-brain pair` writes).
//
//   node tests/adapter_driver.mjs <adapter> <project> <prompt> <reply>
//
// Prints one JSON line: {"adapter", "brief": chars, "context": chars,
// "briefText", "contextText"}. Used by tests/test_adapter_hub_contract.py
// against a fake hub, and by hand against a real one. The platform objects
// are the smallest shapes each adapter reads (see each adapter's header).
import { mkdtempSync, mkdirSync, writeFileSync, copyFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ADAPTERS = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'adapters')
const [adapter, project, prompt, reply] = process.argv.slice(2)
process.env.BRETHOF_BRAIN_PROJECT = project
const sid = 'drv-' + adapter + '-' + Date.now().toString(36)
const text = (t) => [{ type: 'text', text: t }]
const out = { adapter, briefText: '', contextText: '' }

async function load(rel) {
  return (await import(pathToFileURL(join(ADAPTERS, rel)).href)).default
}

function handlers() {
  const on = {}
  return { on, api: { on: (name, fn) => { on[name] = fn } } }
}

if (adapter === 'cline') {
  const p = await load('cline/lib/index.js')
  const user = { role: 'user', content: text(prompt) }
  const r = await p.hooks.beforeModel({ snapshot: { conversationId: sid }, request: { messages: [user] } })
  const overlay = r?.messages?.at(-1)?.content?.[0]?.text || ''
  // the overlay carries brief + context together; split on what the brief call returned
  out.briefText = overlay
  out.contextText = overlay
  await p.hooks.afterRun({ snapshot: { conversationId: sid,
    messages: [user, { role: 'assistant', content: text(reply) }] } })
} else if (adapter === 'opencode') {
  const p = await load('opencode/lib/index.js')
  const msgs = [{ info: { role: 'user' }, parts: text(prompt) },
                { info: { role: 'assistant' }, parts: text(reply) }]
  const hooks = await p.server({ client: { session: { messages: async () => ({ data: msgs }) } } }, {})
  const output = { message: { id: 'msg_1', sessionID: sid }, parts: text(prompt) }
  await hooks['chat.message']({ sessionID: sid }, output)
  const injected = output.parts.filter(x => x.synthetic).map(x => x.text).join('\n\n')
  out.briefText = injected
  out.contextText = injected
  await hooks.event({ event: { type: 'session.idle', properties: { sessionID: sid } } })
} else if (adapter === 'dsh') {
  const p = await load('dsh/lib/index.js')
  const { on, api } = handlers()
  const injected = []
  const agent = { session: { id: sid, snapshotEvents: () => [
    { type: 'turn/start', data: { turn: 1 } },
    { type: 'user/message', data: { source: { kind: 'user' }, content: text(prompt) } },
    { type: 'assistant/message', data: { turn: 1, message: { content: text(reply) } } }] },
    inject: (m) => injected.push(m) }
  p.apply({ on: api.on, logger: console }, {})
  await on['agent/created']({ agent })
  out.briefText = injected.map(m => m.content[0].text).join('\n\n')
  const d = await on['agent/pre-step']({ agent, messages: [{ source: { kind: 'user' }, content: text(prompt) }] },
                                       async () => ({ kind: 'enter', messages: [] }))
  out.contextText = (d?.messages || []).map(m => m.content[0].text).join('\n\n')
  await on['agent/turn-stopping']({ agent })
} else if (adapter === 'amp') {
  const f = await load('amp/brethof-brain.ts')
  const { on, api } = handlers()
  f(api)
  const r = await on['agent.start']({ thread: { id: sid }, message: prompt })
  out.briefText = out.contextText = r?.message?.content || ''
  await on['agent.end']({ thread: { id: sid }, message: prompt, status: 'done',
    messages: [{ role: 'assistant', content: text(reply) }] })
} else if (adapter === 'pi') {
  const f = await load('pi/brethof-brain.ts')
  const { on, api } = handlers()
  f(api)
  const ctx = { sessionManager: { getSessionId: () => sid } }
  await on.session_start({}, ctx)
  const ev = { prompt, systemPromptOptions: { sections: {} } }
  const r = await on.before_agent_start(ev, ctx)
  out.briefText = ev.systemPromptOptions.sections.brethof_brain || ''
  out.contextText = r?.message?.content || ''
  await on.agent_end({ messages: [{ role: 'user', content: text(prompt) },
                                  { role: 'assistant', content: text(reply) }] }, ctx)
} else if (adapter === 'openclaw-gateway' || adapter === 'openclaw-gateway-ts') {
  // the gateway imports openclaw's SDK: a stub package beside a copy of the
  // plugin stands in for it (definePluginEntry returns its argument)
  const dir = mkdtempSync(join(tmpdir(), 'oc-drv-'))
  const sdk = join(dir, 'node_modules', 'openclaw', 'plugin-sdk')
  mkdirSync(sdk, { recursive: true })
  writeFileSync(join(dir, 'node_modules', 'openclaw', 'package.json'),
    JSON.stringify({ name: 'openclaw', type: 'module', exports: { './plugin-sdk/plugin-entry': './plugin-sdk/plugin-entry.js' } }))
  writeFileSync(join(sdk, 'plugin-entry.js'), 'export const definePluginEntry = (e) => e\n')
  const file = adapter === 'openclaw-gateway' ? 'index.mjs' : 'index.ts'
  copyFileSync(join(ADAPTERS, 'openclaw-gateway', file), join(dir, file))
  const entry = (await import(pathToFileURL(join(dir, file)).href)).default
  const { on, api } = handlers()
  entry.register(api)
  const ctx = { sessionId: sid, runId: 'run-1' }
  const r = await on.before_prompt_build({ prompt, context: { pluginConfig: { project } } }, ctx)
  out.briefText = r?.appendSystemContext || ''
  out.contextText = r?.prependContext || ''
  await on.agent_end({ context: { pluginConfig: { project } }, messages: [
    { role: 'user', content: prompt }, { role: 'assistant', content: text(reply) }] }, ctx)
} else {
  console.error('unknown adapter ' + adapter)
  process.exit(2)
}
out.brief = out.briefText.length
out.context = out.contextText.length
console.log(JSON.stringify(out))
