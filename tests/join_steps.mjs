// A small headless-Chrome driver for tests/test_join_checkout.py: open a page
// at a width, run a list of expressions in it one by one (each awaited), and
// report their values with every Stripe stand-in hand-off (/__stripe/) and
// form row (/__form) that left the page. The page is served by
// run.launch_check._serving, which answers both stand-ins.
//
// Usage: node tests/join_steps.mjs <base-url> <chrome-path> <jobs.json>
//   jobs.json: [{"path": "join/index.html", "width": 390, "reduced": false,
//                "steps": ["expression", {"until": "expression", "ms": 5000}, ...]}]
// No dependencies: Node's own WebSocket.

import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, chromePath, jobsFile] = process.argv.slice(2);
const jobs = JSON.parse(readFileSync(jobsFile, "utf8"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "byl-steps-"));
const chrome = spawn(chromePath, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank",
], { stdio: "ignore" });

async function devtoolsPort() {
  const file = join(profile, "DevToolsActivePort");
  for (let i = 0; i < 300; i++) {
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

async function evaluate(s, expression) {
  const r = await s.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) {
    const d = r.exceptionDetails;
    throw new Error((d.exception && d.exception.description) || d.text);
  }
  return r.result.value;
}

async function runJob(port, job) {
  const width = job.width || 390;
  const mobile = width < 768;
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
  const s = session(target.webSocketDebuggerUrl);
  await s.ready;
  const out = { path: job.path, width, values: [], handoffs: [], posted: [], errors: [], error: "" };
  s.on((msg) => {
    if (msg.method === "Network.requestWillBeSent") {
      const req = msg.params.request;
      if (req.url.includes("/__stripe/")) out.handoffs.push(req.url);
      if (req.url.includes("/__form") && req.method === "POST" && req.postData != null) {
        out.posted.push(req.postData);
      }
    } else if (msg.method === "Runtime.exceptionThrown") {
      const d = msg.params.exceptionDetails;
      out.errors.push((d.exception && d.exception.description) || d.text);
    }
  });
  await s.send("Runtime.enable");
  await s.send("Network.enable");
  await s.send("Page.enable");
  await s.send("Emulation.setDeviceMetricsOverride", {
    width, height: mobile ? 844 : 900, deviceScaleFactor: 1, mobile,
  });
  await s.send("Emulation.setEmulatedMedia", { features: [
    { name: "prefers-reduced-motion", value: job.reduced ? "reduce" : "no-preference" }] });
  try {
    const loaded = new Promise((resolve) => s.on((m) => m.method === "Page.loadEventFired" && resolve()));
    await s.send("Page.navigate", { url: base.replace(/\/$/, "") + "/" + job.path });
    await Promise.race([loaded, sleep(15000)]);
    for (const step of job.steps) {
      if (typeof step === "string") {
        out.values.push(await evaluate(s, step));
      } else if (step.until) {
        const end = Date.now() + (step.ms || 8000);
        let ok = false;
        while (Date.now() < end && !ok) {
          ok = Boolean(await evaluate(s, step.until).catch(() => false));
          if (!ok) await sleep(100);
        }
        out.values.push(ok);
      } else if (step.sleep) {
        await sleep(step.sleep);
        out.values.push(null);
      }
    }
  } catch (err) {
    out.error = String(err && err.message || err);
  }
  s.close();
  await fetch(`http://127.0.0.1:${port}/json/close/${target.id}`).catch(() => {});
  return out;
}

const results = [];
try {
  const port = await devtoolsPort();
  for (const job of jobs) {
    try { results.push(await runJob(port, job)); }
    catch (err) { results.push({ path: job.path, error: String(err && err.message || err) }); }
  }
} catch (err) {
  results.push({ fatal: String(err && err.message || err) });
} finally {
  chrome.kill("SIGKILL");
  await sleep(200);
  try { rmSync(profile, { recursive: true, force: true }); } catch {}
}
process.stdout.write(JSON.stringify(results));
