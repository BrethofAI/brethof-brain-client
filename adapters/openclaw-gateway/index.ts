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
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

type Cfg = { endpoint: string; apiKey: string; project: string };

function cfgFrom(pluginConfig: any): Cfg {
  const env = (globalThis as any).process?.env ?? {};
  return {
    endpoint: (pluginConfig?.endpoint || env.BRETHOF_BRAIN_ENDPOINT ||
               "https://api.brethof.cloud").replace(/\/+$/, ""),
    apiKey: pluginConfig?.apiKey || env.BRETHOF_BRAIN_API_KEY || "",
    project: pluginConfig?.project || env.BRETHOF_BRAIN_PROJECT || "openclaw",
  };
}

async function hookPost(cfg: Cfg, path: string, body: object): Promise<any> {
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

/** Tolerant text extraction — agent_end payload shapes vary by version. */
function textOf(x: any, depth = 0): string {
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

const greeted = new Set<string>();          // sessions that got the envelope
const pendingPrompt = new Map<string, string>();   // runId -> user prompt
const nextIndex = new Map<string, number>();       // sessionId -> turn index

export default definePluginEntry({
  id: "brethof-brain",
  name: "brethof-brain memory",
  description: "Persistent cross-session memory via brethof-brain cloud.",
  register(api: any) {
    // NOTE FOR INSTALLERS: agent_end delivers conversation content, and
    // OpenClaw BLOCKS it for non-bundled plugins unless the user opts in:
    //   plugins.entries."brethof-brain".hooks.allowConversationAccess: true
    // Without that line the gateway logs "typed hook agent_end blocked" and
    // memory archival silently never happens (cost a full debugging arc,
    // 2026-08-17). setup docs and the rig both set it.
    api.on("before_prompt_build", async (event: any, ctx: any) => {
      try {
        const cfg = cfgFrom(event?.context?.pluginConfig);
        if (!cfg.apiKey) return;
        const sid = String(ctx?.sessionId ?? ctx?.sessionKey ?? "openclaw");
        const prompt = textOf(event?.prompt);
        if (ctx?.runId != null) pendingPrompt.set(String(ctx.runId), prompt);
        pendingPrompt.set(sid, prompt);   // fallback key — runIds can differ
                                          // between hook families
        const parts: string[] = [];
        if (!greeted.has(sid)) {
          greeted.add(sid);
          const env = await hookPost(cfg, "/v1/hooks/session-start",
                                     { project: cfg.project });
          if (env?.injection) parts.push(String(env.injection));
        }
        if (prompt) {
          const env = await hookPost(cfg, "/v1/hooks/prompt-submit", {
            project: cfg.project, prompt, session_id: sid,
          });
          if (env?.injection) parts.push(String(env.injection));
        }
        if (parts.length) return { appendSystemContext: parts.join("\n\n") };
      } catch {
        /* fail-open — a memory hiccup must never touch the run */
      }
    });

    api.on("agent_end", async (event: any, ctx: any) => {
      try {
        const cfg = cfgFrom(event?.context?.pluginConfig);
        if (!cfg.apiKey) return;
        if ((globalThis as any).process?.env?.BRETHOF_BRAIN_DEBUG) {
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
        const msgs: any[] = Array.isArray(event?.messages)
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
        const turns: object[] = [];
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
