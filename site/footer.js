// The footer map's "This week's report" link. It waits for the landing hero's
// rule, as every link to that page does (launch review PC-01): a current week
// in the season, no later than that week's last game (DATA-02), at least three
// odds and a closest call, on a page built in the report's card layout, with a
// projected total. Anything else leaves it hidden; the sample report is always
// one link away. Reads the site's own week.json and nothing else.
//
// It also closes the season's ask in the Menu, on every footed page: once the
// season is over, or its last week has kicked off, the Menu's gold first item
// (the buy ask, render.report.site_menu) goes to the landing's email capture,
// as the pages' own buttons do, and a free-report link ([data-free-try], the
// league-app pages) hides. The landing closes its own Menu (closeForSeason),
// so a page carrying #watch-form is left to it.
(function () {
  "use strict";
  var links = document.querySelectorAll("footer [data-live-week]");
  var asks = document.querySelectorAll(".sitemenu-list a.go");
  var free = document.querySelectorAll("[data-free-try]");
  if (!(links.length || asks.length || free.length) || !window.fetch) return;
  function easternToday() {
    var part = {};
    new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric",
      month: "2-digit", day: "2-digit" }).formatToParts(new Date())
      .forEach(function (x) { part[x.type] = x.value; });
    return part.year + "-" + part.month + "-" + part.day;
  }
  // The same rule as how-it-works' weekPhase: over by phase, or a last week
  // whose report day has passed, or from the last week's first kickoff.
  function seasonClosed(w, today) {
    var phase = w.phase || "season";
    if (phase === "over") return true;
    if (phase !== "season") return false;
    var last = Number.isInteger(w.week) && Number.isInteger(w.last_week) &&
      w.week >= w.last_week;
    if (!last) return false;
    if (/^\d{4}-\d\d-\d\d$/.test(w.lands_on || "") && today > w.lands_on) return true;
    var kick = Date.parse(w.first_kickoff || "");
    return !isNaN(kick) && Date.now() >= kick;
  }
  function closeAsk(a) {
    var href = a.getAttribute("href") || "";
    var cut = href.indexOf("join/index.html");
    if (cut < 0) return;
    var via = /[?&]via=([a-z0-9-]{1,40})(?:&|#|$)/.exec(href);
    a.setAttribute("href", href.slice(0, cut) + "index.html" +
      (via ? "?via=" + via[1] : "") + "#watch-form");
    a.textContent = "Tell me when it opens";
  }
  fetch("/week.json", { cache: "no-cache" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (w) {
      if (!w) return;
      var today = easternToday();
      if (seasonClosed(w, today)) {
        if (!document.getElementById || !document.getElementById("watch-form")) {
          asks.forEach(closeAsk);
        }
        free.forEach(function (el) { el.hidden = true; });
      }
      if (!links.length || (w.phase || "season") !== "season") return;
      // lands_on is an Eastern date, so "past it" is judged on Eastern time.
      if (!/^\d{4}-\d\d-\d\d$/.test(w.lands_on || "") || today > w.lands_on) return;
      // Only until the week's last game (week_ends, ET): after Monday night
      // the page is about games already played. No week_ends, no link.
      if (!/^\d{4}-\d\d-\d\d$/.test(w.week_ends || "") || today > w.week_ends) return;
      if (Number.isInteger(w.odds) && w.odds >= 3 && w.closest_call && w.cards === true &&
          w.total !== false) {
        links.forEach(function (a) { a.hidden = false; });
      }
    })
    .catch(function () { /* the sample report stands in */ });
})();
