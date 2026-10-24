// The browser half of `make launch-check` (run/launch_check.py).
//
// Loads every page a buyer can reach in real headless Chrome at real phone and
// desktop sizes, over the DevTools protocol, and reports what a test reading
// HTML cannot see. One job file, one Chrome, five kinds of job:
//
//   probe  script errors, failed requests, sideways scrolling, text smaller
//          than a phone can read, tap targets too small to hit, every host a
//          page contacts, and the cookies and storage it leaves (the default)
//   axe    axe-core's accessibility rules, injected after load
//   perf   a phone on Slow 4G with a 4x slower CPU — Largest Contentful Paint
//          and Cumulative Layout Shift, one fresh tab per run
//   flow   the join page completed like a buyer: roster pasted and checked,
//          email typed, button pressed — and the Stripe hand-off URL or the
//          form row it produced captured exactly as it left the page;
//          with "expect": "nothing" (a mode with no form, e.g. a seat page
//          opened without its league's link) it only reads what the page says
//          and records that nothing left it
//
// Usage: node run/launch_browser.mjs <base-url> <chrome-path> <jobs.json>
//   jobs.json: [{"path": "index.html", "widths": [390, 1280]},          // probe
//               {"kind": "axe", "path": ..., "widths": [...], "axe": "/abs/axe.min.js"},
//               {"kind": "perf", "path": ..., "width": 390, "runs": 3},
//               {"kind": "flow", "path": "open/join/index.html?plan=monthly",
//                "width": 390, "mode": "monthly", "roster": "...", "email": "...",
//                "planSwitch": true, "tick": ["settings-ok"], "expect": "nothing"?}]
// Prints one JSON array to stdout. No dependencies: Node's own WebSocket.

import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, chromePath, jobsFile] = process.argv.slice(2);
const jobs = JSON.parse(readFileSync(jobsFile, "utf8"));
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

// Installed before any page script runs (perf jobs): Largest Contentful Paint
// as the browser reports it, and layout shift scored the way Core Web Vitals
// scores it — the worst session window (shifts under 1s apart, at most 5s
// long), shifts right after input excluded.
const VITALS = `(() => {
  const v = window.__vitals = { lcp: null, cls: 0 };
  let session = 0, first = 0, last = 0;
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) v.lcp = e.renderTime || e.loadTime || e.startTime;
    }).observe({ type: "largest-contentful-paint", buffered: true });
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (e.hadRecentInput) continue;
        if (session && (e.startTime - last > 1000 || e.startTime - first > 5000)) session = 0;
        if (!session) first = e.startTime;
        session += e.value; last = e.startTime;
        v.cls = Math.max(v.cls, session);
      }
    }).observe({ type: "layout-shift", buffered: true });
  } catch (err) { v.error = String(err); }
})()`;

// Chrome DevTools' own "Slow 4G" preset, which is the network Lighthouse's
// mobile run models: 150 ms RTT and 1.6 Mbps down, with DevTools' published
// adjustment for request-level throttling (x3.75 latency, x0.9 throughput).
const SLOW_4G = { offline: false, latency: 150 * 3.75,
                  downloadThroughput: 1.6 * 1000 * 1000 / 8 * 0.9,
                  uploadThroughput: 750 * 1000 / 8 * 0.9 };

async function openTab(port, width, { onEvent } = {}) {
  const mobile = width < 768;
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
  const s = session(target.webSocketDebuggerUrl);
  await s.ready;
  const errors = [], failed = [], hosts = new Set();
  s.on((msg) => {
    if (msg.method === "Network.requestWillBeSent") {
      // Every host a page makes the browser contact (ANALYTICS-06): the
      // privacy page says that is only ever our own.
      try {
        const u = new URL(msg.params.request.url);
        if (u.protocol === "http:" || u.protocol === "https:" || u.protocol === "ws:"
            || u.protocol === "wss:") hosts.add(u.host);
      } catch (err) { /* not a URL a page fetched */ }
    }
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
    if (onEvent) onEvent(msg, s);
  });
  await s.send("Runtime.enable");
  await s.send("Network.enable");
  await s.send("Page.enable");
  await s.send("Emulation.setDeviceMetricsOverride", {
    width, height: mobile ? 844 : 900, deviceScaleFactor: mobile ? 3 : 1, mobile,
  });
  if (mobile) await s.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  const close = async () => {
    s.close();
    await fetch(`http://127.0.0.1:${port}/json/close/${target.id}`).catch(() => {});
  };
  return { s, errors, failed, hosts, close };
}

// What a page left behind in the browser: every cookie the profile now holds
// (any site's — a fresh profile starts with none) and the page's own storage.
// The privacy page says nothing is stored on a visitor's device.
async function leftBehind(s) {
  let cookies = [];
  try {
    cookies = (await s.send("Storage.getCookies")).cookies || [];
  } catch (err) {
    cookies = (await s.send("Network.getAllCookies").catch(() => ({ cookies: [] }))).cookies || [];
  }
  const storage = await evaluate(s, `(() => {
    const n = (k) => { try { return window[k].length; } catch (e) { return 0; } };
    return [n("localStorage"), n("sessionStorage")];
  })()`).catch(() => [0, 0]);
  return { cookies: cookies.map((c) => `${c.name} (${c.domain})`), storage };
}

async function navigate(s, path, timeout = 15000) {
  const loaded = new Promise((resolve) => s.on((m) => m.method === "Page.loadEventFired" && resolve()));
  const url = base.replace(/\/$/, "") + "/" + path;
  const started = Date.now();
  await s.send("Page.navigate", { url });
  await Promise.race([loaded, sleep(timeout)]);
  return Date.now() - started;
}

async function evaluate(s, expression, awaitPromise = false) {
  const r = await s.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise });
  if (r.exceptionDetails) {
    const d = r.exceptionDetails;
    throw new Error((d.exception && d.exception.description) || d.text);
  }
  return r.result.value;
}

async function until(s, expression, ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (await evaluate(s, expression).catch(() => false)) return true;
    await sleep(100);
  }
  return false;
}

async function probeJob(port, job) {
  const out = [];
  for (const width of job.widths) {
    const tab = await openTab(port, width);
    const loadMs = await navigate(tab.s, job.path);
    await sleep(job.settle || 2500);           // the hero sequence, late fetches
    const probe = (await evaluate(tab.s, PROBE)) || {};
    // Against the width asked for, not the page's own innerWidth: a phone's
    // layout viewport GROWS to fit content wider than the screen, so a 640px
    // table at 390 reports innerWidth 648 = scrollWidth 648 and "fits".
    probe.overflow = probe.scrollWidth > width + 1 || probe.innerWidth > width + 1;
    const left = await leftBehind(tab.s);
    out.push({ kind: "probe", path: job.path, width, loadMs, errors: tab.errors,
               failed: tab.failed, hosts: [...tab.hosts], ...left, ...probe });
    await tab.close();
  }
  return out;
}

async function axeJob(port, job) {
  const source = readFileSync(job.axe, "utf8");
  const out = [];
  for (const width of job.widths) {
    const tab = await openTab(port, width);
    await navigate(tab.s, job.path);
    await sleep(job.settle || 2500);
    await evaluate(tab.s, source);
    // Only what a person meets: violations, not the "needs review" list, and
    // rules that apply to every page (WCAG 2 A/AA plus best practice).
    const violations = await evaluate(tab.s, `axe.run(document, {
        resultTypes: ["violations"],
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"] },
      }).then((r) => r.violations.map((v) => ({
        id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length,
        target: v.nodes.slice(0, 2).map((n) => n.target.join(" ")) })))`, true);
    out.push({ kind: "axe", path: job.path, width, violations, errors: tab.errors });
    await tab.close();
  }
  return out;
}

async function perfJob(port, job) {
  const lcp = [], cls = [], loadMs = [];
  for (let i = 0; i < (job.runs || 3); i++) {
    const tab = await openTab(port, job.width);
    await tab.s.send("Network.setCacheDisabled", { cacheDisabled: true });
    await tab.s.send("Network.emulateNetworkConditions", SLOW_4G);
    await tab.s.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    await tab.s.send("Page.addScriptToEvaluateOnNewDocument", { source: VITALS });
    loadMs.push(await navigate(tab.s, job.path, 45000));
    await sleep(job.settle || 3000);           // late shifts: fonts, the hero sequence
    const v = await evaluate(tab.s, "window.__vitals || null");
    lcp.push(v && v.lcp != null ? Math.round(v.lcp) : null);
    cls.push(v ? Math.round(v.cls * 1000) / 1000 : null);
    await tab.close();
  }
  return [{ kind: "perf", path: job.path, width: job.width, lcp, cls, loadMs }];
}

// The join page, completed. Stripe links and the form endpoint in the copy
// being served point back at this server (/__stripe/<plan>, /__form), so the
// hand-off and the posted rows are read off the wire as the page sent them.
async function flowJob(port, job) {
  const posted = [];
  let handoff = null;
  const tab = await openTab(port, job.width || 390, {
    onEvent: (msg, s) => {
      if (msg.method !== "Network.requestWillBeSent") return;
      const req = msg.params.request;
      if (req.url.includes("/__stripe/")) handoff = req.url;
      if (req.url.includes("/__form") && req.method === "POST") {
        if (req.postData != null) posted.push(req.postData);
        else s.send("Network.getRequestPostData", { requestId: msg.params.requestId })
          .then((r) => posted.push(r.postData)).catch(() => {});
      }
    },
  });
  const s = tab.s;
  const result = { kind: "flow", mode: job.mode, path: job.path, handoff: null, posted: [],
                   ready: false, tally: "", switched: null, error: "", errors: tab.errors,
                   note: "", mainHidden: false };
  try {
    await navigate(s, job.path);
    if (job.expect === "nothing") {
      // No form to complete: read what the page tells this visitor, press the
      // button if one is still reachable, and record that nothing left.
      await until(s, "document.readyState === 'complete'", 15000);
      await sleep(800);
      Object.assign(result, await evaluate(s, `(() => {
        const note = document.getElementById("closed-note");
        const main = document.getElementById("main");
        const shown = (el) => !!el && getComputedStyle(el).display !== "none";
        const button = document.getElementById("submit");
        if (button && button.offsetParent !== null) button.click();
        // mainHidden: nothing of the form is left on screen (the note itself
        // may sit inside <main>, which keeps the page's main landmark).
        const formShown = !!main && shown(main) &&
          [...main.children].some((el) => el !== note && shown(el));
        return { note: shown(note) ? note.textContent.trim() : "", mainHidden: !formShown };
      })()`));
      await sleep(1500);
      result.handoff = handoff;
      result.posted = posted.slice();
      await tab.close();
      return [result];
    }
    if (!await until(s, "typeof state !== 'undefined' && !!state.directory", 15000)) {
      throw new Error("the player list never loaded");
    }
    await evaluate(s, `(() => {
      const box = document.getElementById("roster-text");
      box.value = ${JSON.stringify(job.roster)};
      box.dispatchEvent(new Event("input", { bubbles: true }));
      document.getElementById("resolve").click();
    })()`);
    result.ready = await until(s, "state.ready === true", 5000);
    result.tally = await evaluate(s, "(document.getElementById('tally') || {}).textContent || ''");
    if (!result.ready) throw new Error("the roster was not accepted: " + result.tally);
    const read = `({ button: document.getElementById("submit").textContent.trim(),
                     terms: (document.getElementById("terms-line") || {}).textContent || "" })`;
    if (job.planSwitch) {
      const pick = (plan) => `(() => { const r = document.querySelector('input[name="plan"][value="${plan}"]');
                                       if (!r) return false; r.click(); return true; })()`;
      const before = await evaluate(s, read);
      const can = await evaluate(s, pick("monthly"));
      const after = can ? await evaluate(s, read) : null;
      if (can) await evaluate(s, pick("season"));
      const back = can ? await evaluate(s, read) : null;
      result.switched = { before, after, back };
    }
    await evaluate(s, `(() => {
      document.getElementById("email").value = ${JSON.stringify(job.email)};
      // Boxes the mode asks a buyer to tick first (job.tick), as a buyer would.
      for (const id of ${JSON.stringify(job.tick || [])}) {
        const box = document.getElementById(id);
        if (box && !box.checked) box.click();
      }
      document.getElementById("submit").click();
    })()`);
    // The join page reads the address back before it leaves for Stripe
    // ("Reports go to … — right?"): answer it as a buyer would.
    await sleep(150);
    if (job.whileAsked) {
      // A buyer who changes something while the read-back is open (a setting,
      // a removed row): what leaves the page must be what is on it at the
      // yes, never what was on it when the box opened. If the change closed
      // the box, they press the button again, as a buyer would.
      const refNow = "R.withVia(checkoutRef(), SOURCE)";
      result.refAsked = await evaluate(s, refNow);
      await evaluate(s, job.whileAsked);
      await sleep(150);
      result.closedByChange = await evaluate(s, 'document.getElementById("check-email").hidden');
      if (result.closedByChange) {
        await evaluate(s, 'document.getElementById("submit").click()');
        await sleep(150);
      }
      result.refAtYes = await evaluate(s, refNow);
    }
    await evaluate(s, `(() => {
      const box = document.getElementById("check-email");
      const yes = document.getElementById("check-yes");
      if (box && yes && !box.hidden) yes.click();
    })()`);
    const end = Date.now() + 6000;
    while (Date.now() < end && !handoff && !posted.length) await sleep(100);
    await sleep(300);
    result.handoff = handoff;
    result.posted = posted.slice();
    if (!handoff && !posted.length) {
      result.error = "nothing left the page: " + await evaluate(s,
        "(document.getElementById('err-email') || {}).textContent || ''").catch(() => "");
    }
  } catch (err) {
    result.error = String(err && err.message || err);
  }
  await tab.close();
  return [result];
}

const RUN = { probe: probeJob, axe: axeJob, perf: perfJob, flow: flowJob };

const results = [];
try {
  const port = await devtoolsPort();
  for (const job of jobs) {
    try {
      results.push(...await RUN[job.kind || "probe"](port, job));
    } catch (err) {
      // One page that cannot be measured is a finding about that page, never
      // a reason to lose every other page's results.
      results.push({ kind: job.kind || "probe", path: job.path, jobError: String(err && err.message || err) });
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
