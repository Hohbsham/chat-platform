#!/usr/bin/env node
/**
 * A2A Push Channel — bridges server.py webhooks into Claude Code.
 *
 * server.py _fire_webhook → localhost:8788 → this server → notifications/claude/channel → Claude window
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import http from "node:http";

// ── MCP Channel server ──
const mcp = new Server(
  { name: "a2a-push", version: "1.0.0" },
  {
    capabilities: {
      experimental: { "claude/channel": {} },
    },
    instructions:
      "A2A platform tasks arrive as <channel source='a2a'>...</channel>. When you see a task, claim and complete it.",
  }
);

await mcp.connect(new StdioServerTransport());

// ── HTTP webhook receiver ──
const PORT = 8788;
http
  .createServer(async (req, res) => {
    if (req.method === "GET" && req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, service: "a2a-channel" }));
      return;
    }

    if (req.method === "POST") {
      let body = "";
      for await (const chunk of req) body += chunk;

      try {
        const data = JSON.parse(body);
        const taskId = data.task_id || "?";
        const title = data.title || "Untitled";
        const agent = data.agent || "";

        await mcp.notification({
          method: "notifications/claude/channel",
          params: {
            content: `New task assigned to ${agent}: ${title}\nTask ID: ${taskId}\n\nRun heartbeat or check signals/ to claim it.`,
            meta: {
              task_id: taskId,
              title: title.substring(0, 100),
              agent: agent,
              source: "a2a-platform",
            },
          },
        });

        // Write signal file directly (bypass watcher delay)
        const fs = await import("node:fs");
        const path = await import("node:path");
        const sigDir = "d:/ClothesNetData/chat-platform/signals";
        fs.mkdirSync(sigDir, { recursive: true });
        const sigPath = path.join(sigDir, `${agent}.json`);
        fs.writeFileSync(sigPath, JSON.stringify({
          task_id: taskId, title: title, ts: Date.now() / 1000
        }));

        // Ghost key injection — wakes Claude Code via simulated keystroke
        const { exec } = await import("node:child_process");
        exec("python d:/ClothesNetData/chat-platform/channel/ghost_key.py", (err) => {
          if (!err) console.error("[a2a-channel] Ghost key injected");
        });

        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true, pushed: true, ghost_key: true }));
      } catch (e) {
        // Non-JSON body — push as plain text
        await mcp.notification({
          method: "notifications/claude/channel",
          params: {
            content: body.substring(0, 1000),
            meta: { source: "a2a-platform" },
          },
        });
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true, pushed: true }));
      }
      return;
    }

    res.writeHead(404);
    res.end("Not found");
  })
  .listen(PORT, "127.0.0.1", () => {
    console.error(`[a2a-channel] Listening on http://127.0.0.1:${PORT}`);
  });
