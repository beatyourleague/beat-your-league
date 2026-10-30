// The footer map's "This week's report" link. It waits for the landing hero's
// rule, as every link to that page does (launch review PC-01): a current week
// in the season, at least three odds and a closest call, on a page built in
// the report's card layout. Anything else leaves it hidden; the sample report
// is always one link away. Reads the site's own week.json and nothing else.
(function () {
  "use strict";
  var links = document.querySelectorAll("footer [data-live-week]");
  if (!links.length || !window.fetch) return;
  fetch("/week.json", { cache: "no-cache" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (w) {
      if (!w || (w.phase || "season") !== "season") return;
      // lands_on is an Eastern date, so "past it" is judged on Eastern time.
      var part = {};
      new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric",
        month: "2-digit", day: "2-digit" }).formatToParts(new Date())
        .forEach(function (x) { part[x.type] = x.value; });
      var today = part.year + "-" + part.month + "-" + part.day;
      if (!/^\d{4}-\d\d-\d\d$/.test(w.lands_on || "") || today > w.lands_on) return;
      if (Number.isInteger(w.odds) && w.odds >= 3 && w.closest_call && w.cards === true) {
        links.forEach(function (a) { a.hidden = false; });
      }
    })
    .catch(function () { /* the sample report stands in */ });
})();
