// XHS signer — 双模式：
//   stdio    (默认，无参数): 父进程通过 stdin/stdout 行协议交互；适合 one-shot
//   socket   (--socket=<path>): 监听 unix socket，多客户端共享；适合常驻
//
// 行协议：
//   request:  {"id":N,"path":"/api/...","body":<obj|null>}\n
//   response: {"id":N,"X-s":"...","X-t":<ms>}\n  或  {"id":N,"error":"..."}\n
//
// 环境变量：
//   XHS_COOKIE  必须，jsdom document.cookie 的初始值
//   XHS_UA      可选，UserAgent

const fs = require("fs");
const net = require("net");
const path = require("path");
const readline = require("readline");
const { JSDOM } = require("jsdom");

const COOKIE = process.env.XHS_COOKIE || "";
const UA = process.env.XHS_UA || "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36";

if (!COOKIE) {
  process.stderr.write("[signer] XHS_COOKIE env required\n");
  process.exit(1);
}

let socketPath = null;
for (const a of process.argv.slice(2)) {
  if (a.startsWith("--socket=")) socketPath = a.slice("--socket=".length);
}

// jsdom warnings 静音
const _origConsoleErr = console.error;
console.error = function (...args) {
  if (typeof args[0] === "string" && (
    args[0].includes("Not implemented") ||
    args[0].includes("HTMLCanvasElement")
  )) return;
  _origConsoleErr.apply(console, args);
};

const dom = new JSDOM(`<!DOCTYPE html><html><body></body></html>`, {
  url: "https://www.xiaohongshu.com/explore",
  referrer: "https://www.xiaohongshu.com/",
  userAgent: UA,
  pretendToBeVisual: true,
  runScripts: "outside-only",
});
const win = dom.window;
for (const part of COOKIE.split("; ")) {
  if (part) win.document.cookie = part + "; domain=.xiaohongshu.com; path=/";
}
win.eval(fs.readFileSync(__dirname + "/ds.js", "utf8"));
win.eval(fs.readFileSync(__dirname + "/sign.js", "utf8"));
if (typeof win._webmsxyw !== "function") {
  process.stderr.write("[signer] _webmsxyw not installed\n");
  process.exit(2);
}

function handle(line) {
  let req;
  try { req = JSON.parse(line); } catch (e) {
    return JSON.stringify({ error: "invalid json: " + e.message });
  }
  const { id, path: p, body } = req;
  try {
    const sig = win._webmsxyw(p, body === null ? undefined : body);
    return JSON.stringify({ id, "X-s": sig["X-s"], "X-t": sig["X-t"] });
  } catch (e) {
    return JSON.stringify({ id, error: e.message });
  }
}

if (socketPath) {
  // socket 模式
  try { fs.unlinkSync(socketPath); } catch {}

  const server = net.createServer((conn) => {
    let buf = "";
    conn.on("data", (chunk) => {
      buf += chunk.toString("utf8");
      let idx;
      while ((idx = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, idx);
        buf = buf.slice(idx + 1);
        if (line.trim()) conn.write(handle(line) + "\n");
      }
    });
    conn.on("error", () => {});
  });

  const cleanup = () => {
    try { fs.unlinkSync(socketPath); } catch {}
    process.exit(0);
  };
  process.on("SIGINT", cleanup);
  process.on("SIGTERM", cleanup);
  process.on("SIGHUP", cleanup);

  server.listen(socketPath, () => {
    fs.chmodSync(socketPath, 0o600);
    process.stderr.write(`[signer] socket listening at ${socketPath}\n`);
  });
} else {
  // stdio 模式
  process.stderr.write("[signer] ready\n");
  const rl = readline.createInterface({ input: process.stdin });
  rl.on("line", (line) => {
    if (!line.trim()) return;
    process.stdout.write(handle(line) + "\n");
  });
  rl.on("close", () => process.exit(0));
}
