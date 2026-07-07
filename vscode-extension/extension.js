/**
 * A2A Task Watcher — VSCode Thin Wrapper Extension
 *
 * ONE job: open Claude CLI terminal + inject tasks into it.
 * Claude CLI interactive mode = same brain as VSCode Extension.
 * Extension injects via terminal.sendText → Claude reads → does work.
 */
const vscode = require("vscode");
const fs = require("fs");
const path = require("path");

const INBOX = "d:/ClothesNetData/chat-platform/inbox";
const SIGNALS = "d:/ClothesNetData/chat-platform/signals";
const CLI = "C:/Users/YANGZ/AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/cli-wrapper.cjs";

/** @param {vscode.ExtensionContext} context */
function activate(context) {
  [INBOX, SIGNALS].forEach((d) => {
    if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
  });

  // ── Shared state ──
  let claudeTerminal = null;
  const processed = new Set();

  // ── Start Claude CLI in a dedicated terminal ──
  function startClaudeCLI() {
    if (claudeTerminal) {
      claudeTerminal.dispose();
    }
    claudeTerminal = vscode.window.createTerminal({
      name: "Claude (A2A Worker)",
      cwd: "d:/ClothesNetData/chat-platform",
      shellPath: "D:/PyCharm/Git/usr/bin/bash.exe",  // Use bash, not PowerShell
    });
    claudeTerminal.sendText(`node "${CLI}" --model deepseek-v4-pro`);
    claudeTerminal.show(false);
    console.log("[A2A Watcher] Claude CLI terminal started");
  }

  // ── Inject task into Claude CLI ──
  function injectTask(task) {
    if (!claudeTerminal || claudeTerminal.exitStatus !== undefined) {
      startClaudeCLI();
    }
    const taskId = task.task_id || "?";
    const title = task.title || "Untitled";
    claudeTerminal.show(true);
    claudeTerminal.sendText(
      `\n[A2A Task] ${title}\nTask ID: ${taskId}\n`
    );
    claudeTerminal.sendText(
      `Read the platform DB, inspect agent outputs with 8-dim detection, complete task ${taskId}. Use Bash for DB queries and Python for A2A API calls.`
    );
    console.log(`[A2A Watcher] Task injected: ${title}`);
  }

  // ── File watcher ──
  const watcher = vscode.workspace.createFileSystemWatcher(
    new vscode.RelativePattern(vscode.Uri.file(INBOX), "*.json")
  );

  function handleNewFile(filePath) {
    if (processed.has(filePath)) return;
    processed.add(filePath);
    if (processed.size > 100) [...processed].slice(0, 50).forEach((f) => processed.delete(f));
    try {
      const task = JSON.parse(fs.readFileSync(filePath, "utf-8"));
      if (task.agent && task.agent !== "QualityEvaluator") return;
      // Write signal
      fs.writeFileSync(
        path.join(SIGNALS, "QualityEvaluator.json"),
        JSON.stringify({ task_id: task.task_id, title: task.title, ts: Date.now() / 1000 })
      );
      injectTask(task);
    } catch (e) {
      console.error("[A2A Watcher] Error:", e.message);
    }
  }

  watcher.onDidCreate((uri) => handleNewFile(uri.fsPath));
  watcher.onDidChange((uri) => handleNewFile(uri.fsPath));
  context.subscriptions.push(watcher);

  // ── Commands ──
  context.subscriptions.push(
    vscode.commands.registerCommand("a2a-task-watcher.startCLI", startClaudeCLI)
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("a2a-task-watcher.checkInbox", () => {
      if (!fs.existsSync(INBOX)) return;
      fs.readdirSync(INBOX).filter((f) => f.endsWith(".json")).forEach((f) => {
        handleNewFile(path.join(INBOX, f));
      });
    })
  );

  // ── Activate ──
  startClaudeCLI();
  vscode.window.showInformationMessage("[A2A] Claude CLI Worker started — monitoring inbox/");

  // ── Background polling: check inbox every 60s, 0 noise when idle ──
  function pollInbox() {
    if (!fs.existsSync(INBOX)) return;
    const files = fs.readdirSync(INBOX).filter((f) => f.endsWith(".json"));
    if (files.length === 0) return;  // Silent — nothing to do
    // Task found! Inject into CLI
    files.forEach((f) => handleNewFile(path.join(INBOX, f)));
  }
  setInterval(pollInbox, 60000);  // Every 60 seconds
  pollInbox();  // First check immediately

  console.log("[A2A Watcher] Background polling started (60s interval, silent when idle)");
}

function deactivate() {}
module.exports = { activate, deactivate };
