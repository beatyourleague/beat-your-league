/* The rookie report page's email box (render/rookies.py). It posts one row to
   the form Worker and shows what happened. The page renders the form only when
   the Worker exists, so nothing here runs on a page that can't save anything. */
(function () {
  "use strict";
  // run/rosters.py _EMAIL_RE, the Worker's and the join page's rule (D14).
  var EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  var VIA_RE = /^[a-z0-9-]{1,24}$/;
  var form = document.getElementById("rookie-ask");
  if (!form) return;
  var endpoint = form.getAttribute("data-endpoint");
  var box = document.getElementById("rookie-email");
  var button = form.querySelector("button");
  var msg = document.getElementById("rookie-msg");
  if (!endpoint || !box || !button || !msg) return;

  function say(text) { msg.textContent = text; }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var email = box.value.trim();
    if (!EMAIL_RE.test(email)) {
      say("That email doesn't look right. Check it and try again.");
      return;
    }
    var row = { kind: "rookie_ask", email: email };
    var via = new URLSearchParams(location.search).get("via") || "";
    if (VIA_RE.test(via)) row.via = via;
    button.disabled = true;
    say("Saving…");
    fetch(endpoint, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(row),
      signal: window.AbortSignal && AbortSignal.timeout ? AbortSignal.timeout(15000) : undefined
    }).then(function (response) {
      if (!response.ok) throw new Error("refused");
      form.querySelector(".ask-row").hidden = true;
      say("You're on the list. The next rookie report comes after the NFL Draft.");
    }).catch(function () {
      button.disabled = false;
      say("That didn't go through, and nothing was saved. Try again in a minute.");
    });
  });
})();
