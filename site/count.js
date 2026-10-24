// The site's own page counter (contract C1; privacy policy section 3).
//
// One short line per page view and per signup step, posted to OUR form Worker
// (forms.beatyourleague.com/e), which adds it to a Cloudflare Analytics Engine
// dataset that keeps counts for three months. The line is six short words —
// which event, which page, the ?via= channel tag, the referring site's host,
// phone or desktop, and (for a buy press) whether checkout was open — and that
// is everything that leaves this file:
//   - never a URL, a query string, a ref, an email or anything typed;
//   - never a cookie or any browser storage, so no ID can follow anybody;
//   - nothing at all under Global Privacy Control or Do Not Track, in an
//     automated browser, or on any host but the live site (a local preview
//     and `make launch-check` count nothing);
//   - fire-and-forget: it never throws, never waits and never holds up a
//     navigation, so a counter that is down costs a visitor nothing.
// ENDPOINT stays empty until LAUNCH.md step 5b is done; empty sends nothing.
// The same <script src="/count.js" defer> line is on every public page,
// generated ones included (render.report.COUNT_TAG). The join page names its
// mode in window.bylPage and calls window.bylCount("roster" | "checkout" |
// "waitlist" | "trial").
(function () {
  "use strict";
  // "https://forms.beatyourleague.com/e" once the Worker is live — never a
  // *.workers.dev address (blockers treat another site's beacon as a tracker).
  const ENDPOINT = "";
  const LIVE = "beatyourleague.com";
  const EVENTS = ["view", "roster", "checkout", "waitlist", "trial"];
  // The Worker drops a line any field of which fails this; so does this file.
  const FIELD = /^[a-z0-9.-]{0,40}$/;
  // Page keys by path, with "index.html", ".html" and a trailing slash taken
  // off (GitHub Pages serves /how-it-works as how-it-works.html).
  const PAGES = {
    "": "index", "join": "join", "league-pass": "league-pass",
    "how-it-works": "how-it-works", "thanks": "thanks", "sample-report": "sample",
    "this-week": "this-week", "sample-first-week": "first-week", "404": "404",
  };
  // Real pages with no key of their own. Any path in neither list is GitHub
  // Pages answering with 404.html, so that is what it counts as.
  const OTHER = ["join/confirm", "terms", "privacy", "legal", "compare", "confidence",
                 "projections", "no-call", "backtest", "ledger"];
  // The keys the join page may name for itself (window.bylPage).
  const JOIN_KEYS = ["join", "join-pass", "join-try", "other"];
  const sent = {};

  function pageKey(path, query) {
    const bare = String(path || "/").replace(/index\.html$/, "").replace(/\.html$/, "")
      .replace(/^\/+|\/+$/g, "");
    let page = Object.prototype.hasOwnProperty.call(PAGES, bare) ? PAGES[bare]
             : OTHER.indexOf(bare) >= 0 ? "other" : "404";
    if (page === "join") {
      // The join page names its own mode (window.bylPage, set from the flags
      // it runs on), so a roster restored from the launch email's ?ref= — a
      // League Pass with no ?plan=pass — counts as the pass page it shows.
      const own = window.bylPage;
      if (JOIN_KEYS.indexOf(own) >= 0) return own;
      // Otherwise the same rules read off the address: a seat claim or a
      // roster update is not the buy page, so neither is counted as one.
      const plan = query.get("plan") || "";
      const seat = query.has("pass") && plan !== "pass";
      const update = !seat && query.has("update");
      if (seat || update) page = "other";
      else if (query.get("try") === "1") page = "join-try";
      else if (plan === "pass") page = "join-pass";
    }
    return page;
  }

  function quiet() {
    const nav = window.navigator || {};
    return !ENDPOINT || window.location.protocol !== "https:"
      || window.location.hostname !== LIVE || nav.webdriver === true
      || nav.globalPrivacyControl === true
      || [nav.doNotTrack, window.doNotTrack, nav.msDoNotTrack].some(
        (v) => v === "1" || v === "yes");
  }

  function line(event, state) {
    const query = new URLSearchParams(window.location.search);
    // The same sanitiser every funnel page applies to ?via= before a form row
    // carries it, so a channel counts under one name in both places.
    const via = (query.get("via") || "").toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 24);
    let ref = "";
    try { ref = new URL(document.referrer).hostname.toLowerCase(); } catch (e) { ref = ""; }
    // A step inside the site says so with our own name — still a bare host —
    // so "(direct or hidden)" in make stats means arrivals, not every click
    // from the landing to the join page.
    if (ref === LIVE || ref.endsWith("." + LIVE)) ref = LIVE;
    const row = {
      e: event, p: pageKey(window.location.pathname, query), v: via, r: ref,
      d: (window.innerWidth || 0) < 768 ? "m" : "d",
      s: state === "open" || state === "closed" ? state : "",
    };
    for (const key in row) if (!FIELD.test(row[key])) row[key] = "";
    return row;
  }

  function count(event, state) {
    try {
      if (EVENTS.indexOf(event) < 0 || quiet()) return;
      // Once per kind a page load: a second press of the same button is the
      // same visit, not a second one.
      const once = event + ":" + (state || "");
      if (sent[once]) return;
      sent[once] = true;
      const body = JSON.stringify(line(event, state));
      if (typeof window.fetch === "function") {
        // text/plain: no CORS preflight. No credentials, so no cookie of any
        // site rides along; strict-origin, so the Referer is the bare origin.
        window.fetch(ENDPOINT, {
          method: "POST", body: body, keepalive: true, credentials: "omit",
          referrerPolicy: "strict-origin", cache: "no-store",
          headers: { "Content-Type": "text/plain" },
        }).catch(function () {});
      } else if (window.navigator && window.navigator.sendBeacon) {
        window.navigator.sendBeacon(ENDPOINT, body);
      }
    } catch (e) { /* counting never costs a visitor anything */ }
  }

  window.bylCount = count;
  try {
    // After load, so the counter never competes with what a reader sees first.
    // A page restored from the back-forward cache is the same view, not a new
    // one, and a prerendered page counts only once it is actually shown.
    window.addEventListener("pageshow", function (ev) {
      if (ev && ev.persisted) return;
      if (document.prerendering) {
        document.addEventListener("prerenderingchange", function () { count("view"); },
                                  { once: true });
      } else {
        count("view");
      }
    });
  } catch (e) { /* no counter, same page */ }
})();
