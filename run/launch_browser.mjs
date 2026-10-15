// The browser half of `make launch-check` (run/launch_check.py).
//
// Loads every page a buyer can reach in real headless Chrome at real phone and
// desktop sizes, over the DevTools protocol, and reports what a test reading
// HTML cannot see: script errors, failed requests, sideways scrolling, text
// smaller than a phone can read, tap targets too small to hit.
//
// Usage: node run/launch_browser.mjs <base-url> <chrome-path> <pages.json>
//   pages.json: [{"path": "index.html", "widths": [390, 1280]}, ...]
// Prints one JSON array to stdout. No dependencies: Node's own WebSocket.

import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, chromePath, pagesFile] = process.argv.slice(2);
const pages = JSON.parse(readFileSync(pagesFile, "utf8"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = mkdtempSync(join(tmpdir(), "byl-launch-"));
const chrome = spawn(chromePath, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank",
], { stdio: "ignore" });

async function devtoolsPort() {
  const file = join(profile, "DevToolsActivePort");
  for (let i = 0; i < 100; i++) {
    if (existsSync(file)) {
      const port = readFileSync(file, "utf8").split("\n")[0].trim();
      if (port) return port;
    }
    await sleep(100);
  }
  throw new Error("Chrome did not open a DevTools port");
}

function session(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let id = 0;
  const waiting = new Map();
  const listeners = [];
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && waiting.has(msg.id)) {
      const { resolve, reject } = waiting.get(msg.id);
      waiting.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    } else if (msg.method) {
      listeners.forEach((fn) => fn(msg));
    }
  };
  const ready = new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = () => reject(new Error("DevTools socket failed"));
  });
  return {
    ready,
    send: (method, params = {}) => new Promise((resolve, reject) => {
      const n = ++id;
      waiting.set(n, { resolve, reject });
      ws.send(JSON.stringify({ id: n, method, params }));
    }),
    on: (fn) => listeners.push(fn),
    close: () => ws.close(),
  };
}

// Measured in the page: overflow, legibility and tap targets.
const PROBE = `(() => {
  const vw = window.innerWidth;
  const doc = document.documentElement;
  const visible = (el) => {
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || +s.opacity === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const small = [];
  for (const el of document.querySelectorAll("body *")) {
    if (!el.childNodes.length) continue;
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 2);
    if (!own || !visible(el)) continue;
    // The hero's phone is a picture of a phone: its type is drawn at phone scale.
    if (el.closest("svg, [aria-hidden=true], .phone, .screen")) continue;
    const size = parseFloat(getComputedStyle(el).fontSize);
    if (size < 11) small.push(el.tagName.toLowerCase() + "." + (el.className || "") + " " + size + "px: " + el.textContent.trim().slice(0, 40));
  }
  const taps = [];
  for (const el of document.querySelectorAll("a[href], button, input, select, textarea, summary, label")) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    // A link inside running text is exempt (WCAG 2.5.8): its line is the target.
    if (el.tagName === "A" && getComputedStyle(el).display === "inline") {
      const around = (el.parentElement && el.parentElement.textContent || "").trim().length;
      if (around > (el.textContent || "").trim().length + 15) continue;
    }
    if (r.width < 24 || r.height < 24) taps.push(el.tagName.toLowerCase() + " " + Math.round(r.width) + "x" + Math.round(r.height) + ": " + (el.textContent || el.value || el.name || "").trim().slice(0, 30));
  }
  return {
    title: document.title,
    scrollWidth: doc.scrollWidth, innerWidth: vw,
    overflow: doc.scrollWidth > vw + 1,
    h1: document.querySelectorAll("h1").length,
    imgsWithoutAlt: [...document.querySelectorAll("img")].filter((i) => !i.hasAttribute("alt")).length,
    smallText: small.slice(0, 8), smallTextCount: small.length,
    smallTaps: taps.slice(0, 8), smallTapCount: taps.length,
  };
})()`;

const results = [];
try {
  const port = await devtoolsPort();
  for (const page of pages) {
    for (const width of page.widths) {
      const mobile = width < 768;
      const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
      const s = session(target.webSocketDebuggerUrl);
      await s.ready;
      const errors = [], failed = [];
      s.on((msg) => {
        if (msg.method === "Runtime.exceptionThrown") {
          const d = msg.params.exceptionDetails;
          errors.push((d.exception && d.exception.description) || d.text);
        } else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
          errors.push(msg.params.args.map((a) => a.value || a.description || "").join(" "));
        } else if (msg.method === "Network.responseReceived") {
          const r = msg.params.response;
          if (r.status >= 400) failed.push(`${r.status} ${r.url}`);
        } else if (msg.method === "Network.loadingFailed" && !msg.params.canceled) {
          failed.push(`${msg.params.errorText} (${msg.params.type})`);
        }
      });
      await s.send("Runtime.enable");
      await s.send("Network.enable");
      await s.send("Page.enable");
      await s.send("Emulation.setDeviceMetricsOverride", {
        width, height: mobile ? 844 : 900, deviceScaleFactor: mobile ? 3 : 1, mobile,
      });
      if (mobile) await s.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
      const loaded = new Promise((resolve) => s.on((m) => m.method === "Page.loadEventFired" && resolve()));
      const url = base.replace(/\/$/, "") + "/" + page.path;
      const started = Date.now();
      await s.send("Page.navigate", { url });
      await Promise.race([loaded, sleep(15000)]);
      const loadMs = Date.now() - started;
      await sleep(page.settle || 2500);           // the hero sequence, late fetches
      const probe = await s.send("Runtime.evaluate", { expression: PROBE, returnByValue: true });
      results.push({ path: page.path, width, loadMs, errors, failed, ...(probe.result.value || {}) });
      s.close();
      await fetch(`http://127.0.0.1:${port}/json/close/${target.id}`).catch(() => {});
    }
  }
} catch (err) {
  results.push({ fatal: String(err && err.message || err) });
} finally {
  chrome.kill("SIGKILL");
  await sleep(200);
  try { rmSync(profile, { recursive: true, force: true }); } catch {}
}
process.stdout.write(JSON.stringify(results));
