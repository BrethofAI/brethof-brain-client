import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
function cfgFrom(pluginConfig) {
  const env = globalThis.process?.env ?? {};
  return {
    endpoint: (pluginConfig?.endpoint || env.BRETHOF_BRAIN_ENDPOINT || "http://127.0.0.1:8610").replace(/\/+$/, ""),
    apiKey: pluginConfig?.apiKey || env.BRETHOF_BRAIN_API_KEY || "",
    project: pluginConfig?.project || env.BRETHOF_BRAIN_PROJECT || "openclaw",
    unlockPassphrase: pluginConfig?.unlockPassphrase || env.BRETHOF_BRAIN_UNLOCK_PASSPHRASE || "",
    lockAfterMinutes: parseInt(pluginConfig?.lockAfterMinutes || env.BRETHOF_BRAIN_LOCK_AFTER_MINUTES || "0", 10) || 0
  };
}
async function unlock(cfg) {
  if (!cfg.unlockPassphrase) return false;
  const body = { passphrase: cfg.unlockPassphrase };
  if (cfg.lockAfterMinutes) body.idle_seconds = cfg.lockAfterMinutes * 60;
  try {
    const r = await fetch(cfg.endpoint + "/unlock", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(9e4)
    });
    return r.ok;
  } catch {
    return false;
  }
}
async function hookPost(cfg, path, body, retried = false) {
  const r = await fetch(cfg.endpoint + path, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${cfg.apiKey}`
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(9e3)
  });
  if (r.status === 423 && !retried && await unlock(cfg)) {
    return hookPost(cfg, path, body, true);
  }
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}
function textOf(x, depth = 0) {
  if (!x || depth > 4) return "";
  if (typeof x === "string") return x;
  if (Array.isArray(x)) {
    return x.map((v) => textOf(v, depth + 1)).filter(Boolean).join("\n");
  }
  if (typeof x === "object") {
    return textOf(
      x.text ?? x.content ?? x.message ?? x.output ?? "",
      depth + 1
    );
  }
  return "";
}
const greeted = /* @__PURE__ */ new Set();
const pendingPrompt = /* @__PURE__ */ new Map();
const nextIndex = /* @__PURE__ */ new Map();
var index_default = definePluginEntry({
  id: "brethof-brain",
  name: "brethof-brain memory",
  description: "Persistent cross-session memory via brethof-brain cloud.",
  register(api) {
    api.on("before_prompt_build", async (event, ctx) => {
      try {
        const cfg = cfgFrom(event?.context?.pluginConfig);
        if (!cfg.apiKey) return;
        const sid = String(ctx?.sessionId ?? ctx?.sessionKey ?? "openclaw");
        const prompt = textOf(event?.prompt);
        if (ctx?.runId != null) pendingPrompt.set(String(ctx.runId), prompt);
        pendingPrompt.set(sid, prompt);
        const parts = [];
        if (!greeted.has(sid)) {
          greeted.add(sid);
          const env = await hookPost(
            cfg,
            "/v1/hooks/session-start",
            { project: cfg.project }
          );
          if (env?.injection) parts.push(String(env.injection));
        }
        if (prompt) {
          const env = await hookPost(cfg, "/v1/hooks/prompt-submit", {
            project: cfg.project,
            prompt,
            session_id: sid
          });
          if (env?.injection) parts.push(String(env.injection));
        }
        if (parts.length) return { appendSystemContext: parts.join("\n\n") };
      } catch {
      }
    });
    api.on("agent_end", async (event, ctx) => {
      try {
        const cfg = cfgFrom(event?.context?.pluginConfig);
        if (!cfg.apiKey) return;
        if (globalThis.process?.env?.BRETHOF_BRAIN_DEBUG) {
          try {
            const fs = await import("node:fs");
            fs.appendFileSync(
              "/tmp/brethof-dbg.log",
              "agent_end " + JSON.stringify(event).slice(0, 1200) + "\n"
            );
          } catch {
          }
        }
        const sid = String(ctx?.sessionId ?? ctx?.sessionKey ?? "openclaw");
        const msgs = Array.isArray(event?.messages) ? event.messages : [];
        const lastA = [...msgs].reverse().find((m) => m?.role === "assistant");
        const lastU = [...msgs].reverse().find((m) => m?.role === "user");
        const prompt = pendingPrompt.get(String(ctx?.runId ?? "")) ?? pendingPrompt.get(sid) ?? textOf(lastU?.content);
        pendingPrompt.delete(String(ctx?.runId ?? ""));
        pendingPrompt.delete(sid);
        const answer = textOf(lastA?.content);
        let idx = nextIndex.get(sid) ?? 0;
        const turns = [];
        if (prompt) turns.push({ index: idx++, line_type: "user", text: prompt });
        if (answer) turns.push({ index: idx++, line_type: "assistant", text: answer });
        nextIndex.set(sid, idx);
        if (turns.length) {
          await hookPost(
            cfg,
            "/v1/hooks/stop",
            { project: cfg.project, session_id: sid, turns }
          );
        }
      } catch {
      }
    });
  }
});
export {
  index_default as default
};
