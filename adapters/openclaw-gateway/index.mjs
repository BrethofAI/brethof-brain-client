// Generated from index.ts (node:module stripTypeScriptTypes) — edit index.ts, not this file.
/**
 * brethof-brain memory for the OpenClaw gateway — the three-hook contract:
 *
 *   before_prompt_build  -> session-start injection (first turn of a session)
 *                           + ambient recall for the current prompt,
 *                           delivered via appendSystemContext
 *   agent_end            -> the finished turn archived (fire-and-forget)
 *
 * Every path is fail-open: memory can never block or break a run. Explicit
 * memory TOOLS (search_brain, save_project, ...) are deliberately NOT
 * registered here — point OpenClaw's native MCP client at the same endpoint
 * instead (see README), one config block, zero duplicate surface.
 */
import { appendFileSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

                                                                 

// The file `brethof-brain pair` writes: {endpoint, api_key, ...} — the same
// one every adapter reads (BRETHOF_BRAIN_HOME moves it). Read per call, so a
// device paired while the gateway runs is picked up without a restart.
function fileConfig()      {
  try {
    const env = (globalThis       ).process?.env ?? {};
    const home = env.BRETHOF_BRAIN_HOME || join(homedir(), ".brethof-brain");
    return JSON.parse(readFileSync(join(home, "config.json"), "utf8")) || {};
  } catch {
    return {};
  }
}

function cfgFrom(pluginConfig     )      {
  const env = (globalThis       ).process?.env ?? {};
  const f = fileConfig();
  return {
    endpoint: (pluginConfig?.endpoint || env.BRETHOF_BRAIN_ENDPOINT ||
               f.endpoint || "http://127.0.0.1:8600").replace(/\/+$/, ""),
    apiKey: pluginConfig?.apiKey || env.BRETHOF_BRAIN_API_KEY || f.api_key || "",
    project: pluginConfig?.project || env.BRETHOF_BRAIN_PROJECT || "openclaw",
  };
}

// THE HUB'S FRONT DOOR (local-first, 2026-11-20): the device key travels as
// a Bearer token — the hub refuses any other header. The memory never locks, so a refusal is just a failure.
async function hookPost(cfg     , path        , body        )               {
  const r = await fetch(cfg.endpoint + path, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${cfg.apiKey}`,
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(9000),
  });
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

// PROMPT CONTEXT IN PARTS 1-7, as the Claude Code plugin receives it: records
// and rules in 1-6, the history of decisions near the prompt in 7 (no part =
// the legacy blob, which never carries that history). Asked in parallel, so
// the wall time stays one request's 9 s; a failed part is simply left out.
async function promptContext(cfg     , body        )                  {
  const got = await Promise.allSettled([1, 2, 3, 4, 5, 6, 7].map((part) =>
    hookPost(cfg, "/v1/hooks/prompt-submit", { ...body, part })));
  return got.map((r) => r.status === "fulfilled" ? String(r.value?.injection || "").trim() : "")
    .filter(Boolean).join("\n\n");
}

/** Tolerant text extraction — agent_end payload shapes vary by version. */
function textOf(x     , depth = 0)         {
  if (!x || depth > 4) return "";
  if (typeof x === "string") return x;
  if (Array.isArray(x)) {
    return x.map((v) => textOf(v, depth + 1)).filter(Boolean).join("\n");
  }
  if (typeof x === "object") {
    return textOf(x.text ?? x.content ?? x.message ?? x.output ?? "",
                  depth + 1);
  }
  return "";
}

const greeted = new Set        ();          // sessions that got the envelope
const pendingPrompt = new Map                ();   // runId -> user prompt
const nextIndex = new Map                ();       // sessionId -> turn index

export default definePluginEntry({
  id: "brethof-brain",
  name: "brethof-brain memory",
  description: "Persistent cross-session memory from your Brain hub.",
  register(api     ) {
    // NOTE FOR INSTALLERS: agent_end delivers conversation content, and
    // OpenClaw BLOCKS it for non-bundled plugins unless the user opts in:
    //   plugins.entries."brethof-brain".hooks.allowConversationAccess: true
    // Without that line the gateway logs "typed hook agent_end blocked" and
    // memory archival silently never happens (cost a full debugging arc,
    // 2026-08-17). setup docs and the rig both set it.
    // DIAGNOSTICS, off unless BRETHOF_BRAIN_DEBUG_FILE is set (2026-09-30:
    // which hook fires on which turn, with how much prompt — OpenClaw 2026.9
    // stopped delivering per-turn recall and the cause is in that order)
    const dbg = (o     ) => {
      const f = process.env.BRETHOF_BRAIN_DEBUG_FILE;
      if (!f) return;
      try { appendFileSync(f, JSON.stringify({ t: Date.now(), ...o }) + "\n"); } catch { /* never the run's failure */ }
    };
    api.on("agent_turn_prepare", async (event     , ctx     ) => {
      dbg({ hook: "agent_turn_prepare", promptLen: String(event?.prompt ?? "").length, runId: ctx?.runId ?? null, sid: ctx?.sessionId ?? ctx?.sessionKey ?? null });
    });
    api.on("before_prompt_build", async (event     , ctx     ) => {
      try {
        const cfg = cfgFrom(event?.context?.pluginConfig);
        if (!cfg.apiKey) return;
        const sid = String(ctx?.sessionId ?? ctx?.sessionKey ?? "openclaw");
        const prompt = textOf(event?.prompt);
        dbg({ hook: "before_prompt_build", promptLen: prompt.length, rawType: typeof event?.prompt, runId: ctx?.runId ?? null, sid, greeted: greeted.has(sid) });
        if (ctx?.runId != null) pendingPrompt.set(String(ctx.runId), prompt);
        pendingPrompt.set(sid, prompt);   // fallback key — runIds can differ
                                          // between hook families
        const parts           = [];      // session start: static for the session
        let recall = "";                     // per prompt: this turn only
        if (!greeted.has(sid)) {
          greeted.add(sid);
          const env = await hookPost(cfg, "/v1/hooks/session-start",
                                     { project: cfg.project });
          if (env?.injection) parts.push(String(env.injection));
        }
        if (prompt) {
          recall = await promptContext(cfg, {
            project: cfg.project, prompt, session_id: sid,
          });
        }
        // OpenClaw 2026.9 caches the system prompt per session: appendSystemContext
        // is for static text (the session start) and a per-turn addition there
        // never reaches the model after turn one (rig 2026-09-29, 2026.9.2:
        // inject yes, recall no). Per-turn context goes in prependContext,
        // as OpenClaw's hooks docs now direct.
        const out                         = {};
        if (parts.length) out.appendSystemContext = parts.join("\n\n");
        if (recall) out.prependContext = recall;
        if (parts.length || recall) return out;

      } catch {
        /* fail-open — a memory hiccup must never touch the run */
      }
    });

    api.on("agent_end", async (event     , ctx     ) => {
      try {
        const cfg = cfgFrom(event?.context?.pluginConfig);
        if (!cfg.apiKey) return;
        if ((globalThis       ).process?.env?.BRETHOF_BRAIN_DEBUG) {
          try {
            const fs = await import("node:fs");
            fs.appendFileSync("/tmp/brethof-dbg.log",
              "agent_end " + JSON.stringify(event).slice(0, 1200) + "\n");
          } catch { /* debug only */ }
        }
        const sid = String(ctx?.sessionId ?? ctx?.sessionKey ?? "openclaw");
        // Real agent_end shape (captured live, OpenClaw 2026.7.1): the
        // event is {messages: [full history], success, runId} — the turn's
        // answer is the LAST role:"assistant" entry (Claude-style content
        // blocks), the turn's prompt the last role:"user". Joining the
        // whole history archived prompt-blobs as "assistant" turns.
        const msgs        = Array.isArray(event?.messages)
          ? event.messages : [];
        const lastA = [...msgs].reverse()
          .find((m) => m?.role === "assistant");
        const lastU = [...msgs].reverse().find((m) => m?.role === "user");
        const prompt = pendingPrompt.get(String(ctx?.runId ?? "")) ??
                       pendingPrompt.get(sid) ?? textOf(lastU?.content);
        pendingPrompt.delete(String(ctx?.runId ?? ""));
        pendingPrompt.delete(sid);
        const answer = textOf(lastA?.content);
        let idx = nextIndex.get(sid) ?? 0;
        const turns           = [];
        if (prompt) turns.push({ index: idx++, line_type: "user", text: prompt });
        if (answer) turns.push({ index: idx++, line_type: "assistant", text: answer });
        nextIndex.set(sid, idx);
        if (turns.length) {
          await hookPost(cfg, "/v1/hooks/stop",
                         { project: cfg.project, session_id: sid, turns });
        }
      } catch {
        /* fail-open */
      }
    });
  },
});
