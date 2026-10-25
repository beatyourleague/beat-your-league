// The bye-week planner's rule, in the browser. THE OTHER HALF IS
// engine/preseason.py (unfillable_slots, bye_collisions, _out_names) and
// engine/history.py FLEX_ELIGIBILITY; tests/test_polish_tool.py runs this file
// under node against the Python on the same rosters. If they disagree, the
// free planner and the weekly report's "Byes ahead" tell one manager two
// different things about the same week.
//
// Facts only: a week is flagged when a bye leaves a starting slot that nothing
// else on the roster can fill (RULE P2) — off the published schedule and
// today's reserve list. No projection, no percentage, nothing about how
// anybody will play. The words below say that and nothing more.
//
// One IIFE, one global (B): a plain <script> shares the page's global scope
// with roster.js, and a second top-level name there is a SyntaxError that
// silently stops every script on the page.
(function () {
  "use strict";

  const FLEX_ELIGIBILITY = {
    FLEX: ["RB", "WR", "TE"],
    WRRB_FLEX: ["RB", "WR"],
    REC_FLEX: ["WR", "TE"],
    SUPER_FLEX: ["QB", "RB", "WR", "TE"],
    IDP_FLEX: ["DL", "LB", "DB"],
  };

  function restrictiveness(slot) {
    const allowed = FLEX_ELIGIBILITY[slot];
    return allowed ? allowed.length : 1;
  }

  function eligible(slot, position) {
    const allowed = FLEX_ELIGIBILITY[slot];
    return allowed ? allowed.indexOf(position) >= 0 : position === slot;
  }

  // Python's sorted() on str compares code points; every id here is ASCII
  // ("00-0036963", "DEF-KC") and every name is in the BMP, where that equals
  // JavaScript's code-unit order.
  function byCodePoint(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

  // Mirrors unfillable_slots: greedy in (restrictiveness, slot, index) order,
  // each slot taking the lowest-id eligible player still in the pool.
  function unfillableSlots(slots, available) {
    const pool = new Map(Object.entries(available));
    const empty = [];
    const order = slots.map((_, i) => i).sort((i, j) =>
      (restrictiveness(slots[i]) - restrictiveness(slots[j]))
      || byCodePoint(slots[i], slots[j]) || (i - j));
    for (const index of order) {
      const slot = slots[index];
      const ids = [...pool.keys()].sort(byCodePoint);
      const taken = ids.find((id) => eligible(slot, pool.get(id)));
      if (taken === undefined) empty.push(slot);
      else pool.delete(taken);
    }
    return empty;
  }

  function counter(list) {
    const c = new Map();
    for (const x of list) c.set(x, (c.get(x) || 0) + 1);
    return c;
  }

  // Counter subtraction: keep only positive counts (Python's Counter - Counter),
  // in the first counter's insertion order.
  function subtract(a, b) {
    const out = new Map();
    for (const [k, v] of a) {
      const left = v - (b.get(k) || 0);
      if (left > 0) out.set(k, left);
    }
    return out;
  }

  function elements(c) {
    const out = [];
    for (const [k, v] of c) for (let i = 0; i < v; i++) out.push(k);
    return out;
  }

  function outNames(roster, slots, exclude) {
    return roster.filter((r) => r.out_today && !exclude.has(r.player_id)
        && slots.some((slot) => eligible(slot, r.position)))
      .map((r) => r.name + " (" + r.out_today + ")").sort(byCodePoint);
  }

  function positions(rows) {
    const out = {};
    rows.forEach((r) => { out[r.player_id] = r.position; });
    return out;
  }

  // The slots today's reserve list empties in EVERY week: the always_empty
  // Counter difference in bye_collisions, as a list. Not a bye problem — the
  // page says it once, above the weeks, with the reason.
  function thinSlots(roster, slots) {
    const known = roster.filter((r) => r.position !== "UNK");
    const canPlay = known.filter((r) => !r.out_today);
    return elements(subtract(counter(unfillableSlots(slots, positions(canPlay))),
                             counter(unfillableSlots(slots, positions(known)))));
  }

  // Slots the roster cannot fill even with everybody on it counted: a hole
  // that has nothing to do with byes (no kicker on a roster whose league
  // starts one). The page asks for the roster to be fixed instead of
  // listing seventeen identical weeks.
  function structural(roster, slots) {
    return unfillableSlots(slots, positions(roster.filter((r) => r.position !== "UNK")));
  }

  // Mirrors bye_collisions. roster rows: {player_id, name, position, bye, out_today}.
  function byeCollisions(roster, slots, weeks) {
    const canPlay = roster.filter((r) => r.position !== "UNK" && !r.out_today);
    const onRoster = positions(roster.filter((r) => r.position !== "UNK"));
    const alwaysEmpty = subtract(counter(unfillableSlots(slots, positions(canPlay))),
                                 counter(unfillableSlots(slots, onRoster)));
    const out = [];
    for (const week of weeks) {
      const idle = new Set(roster.filter((r) => r.bye === week).map((r) => r.player_id));
      if (!idle.size) continue;
      const available = positions(canPlay.filter((r) => !idle.has(r.player_id)));
      const skip = new Map(alwaysEmpty);
      const empty = [];
      for (const slot of unfillableSlots(slots, available)) {
        if (skip.get(slot)) skip.set(slot, skip.get(slot) - 1);
        else empty.push(slot);
      }
      if (!empty.length) continue;
      out.push({
        week,
        slots: empty,
        players: roster.filter((r) => idle.has(r.player_id)).map((r) => r.name).sort(byCodePoint),
        short: roster.filter((r) => idle.has(r.player_id)
            && empty.some((slot) => eligible(slot, r.position)))
          .map((r) => r.name).sort(byCodePoint),
        out: outNames(roster, empty, idle),
      });
    }
    return out;
  }

  // ------------------------------------------------------------------ words

  // engine.solo_report: _SLOT_WORDS and _SLOT_ORDER, the weekly report's own.
  const SLOT_WORDS = { SUPER_FLEX: "SFLEX", WRRB_FLEX: "W/R", REC_FLEX: "W/T" };
  const SLOT_ORDER = ["QB", "RB", "WR", "TE", "FLEX", "WRRB_FLEX", "REC_FLEX",
                      "SUPER_FLEX", "K", "DEF"];
  // Weeks 15-17: the playoffs under ESPN's, Yahoo's and Sleeper's defaults
  // (engine.solo_report.DEFAULT_PLAYOFF_WEEKS), 17 the title game.
  const PLAYOFF_WEEKS = [15, 16, 17];
  const TITLE_WEEK = 17;
  const LAST_PLANNED = 17;

  function joinWords(words) {
    if (words.length <= 1) return words[0] || "";
    if (words.length === 2) return words[0] + " and " + words[1];
    return words.slice(0, -1).join(", ") + " and " + words[words.length - 1];
  }

  // ["K", "DEF"] -> "K and DEF"; ["RB", "RB", "TE"] -> "2 RB and TE".
  function slotWords(slots) {
    const rank = (slot) => (SLOT_ORDER.indexOf(slot) < 0 ? SLOT_ORDER.length
                                                         : SLOT_ORDER.indexOf(slot));
    const counts = counter(slots.slice().sort((a, b) => rank(a) - rank(b)));
    return joinWords([...counts].map(([slot, n]) =>
      (n > 1 ? n + " " : "") + (SLOT_WORDS[slot] || slot)));
  }

  // The week being played: the first week whose regular window ends today or
  // later — run.solo.current_week's rule, on byes.json's "ends" — or null once
  // every week has ended.
  function currentWeek(byes, todayIso) {
    for (const w of byes.weeks) if (w.ends >= todayIso) return w.week;
    return null;
  }

  function byeWeekOf(byes) {
    const out = {};
    byes.weeks.forEach((w) => w.bye.forEach((team) => { out[team] = w.week; }));
    return out;
  }

  // The rows the rule reads, built the way run.solo._byes_ahead builds them:
  // the bye from the player's current team, today's reserve-list reason or null.
  function rosterRows(players, byes) {
    const week = byeWeekOf(byes);
    const out = byes.out || {};
    return players.map((p) => ({
      player_id: p.id, name: p.name, position: p.position,
      bye: p.team && week[p.team] !== undefined ? week[p.team] : null,
      out_today: out[p.id] || null,
    }));
  }

  // "WR · DET · bye Week 6", "· bye already played", "· on injured reserve".
  function rowMeta(player, row, from) {
    const bits = [player.position, player.team].filter(Boolean);
    if (row.bye !== null) bits.push(from !== null && row.bye < from ? "bye already played"
                                                                     : "bye Week " + row.bye);
    if (row.out_today) bits.push(row.out_today);
    return bits.join(" · ");
  }

  function etDay(iso) {
    try {
      return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York",
        weekday: "short", month: "short", day: "numeric" }).format(new Date(iso));
    } catch (err) {
      return "";
    }
  }

  const FOOTNOTE = "*Under ESPN's, Yahoo's and Sleeper's default settings, Weeks 15–17 " +
    "are the fantasy playoffs and Week 17 is the title game. Yours is in your league settings.";

  function weekList(weeks) {
    return joinWords(weeks.map((w) => "Week " + w));
  }

  // Everything the results show, as words: the page only puts them on screen.
  // kind: "over" (no week left to plan), "structural" (the roster can't fill a
  // slot in any week), or "plan".
  function describe(roster, slots, byes, todayIso) {
    const season = String(byes.season);
    const current = currentWeek(byes, todayIso);
    const through = Math.min(LAST_PLANNED, byes.last_week);
    if (current === null || current > through) {
      return { kind: "over", season,
        summary: "The " + season + " season's bye weeks are behind us. The planner " +
          "opens again when next season's schedule is out." };
    }
    const from = current;
    const holes = structural(roster, slots);
    if (holes.length) {
      const one = holes.length === 1;
      const optional = [];
      if (holes.indexOf("K") >= 0) optional.push("Kicker to No K");
      if (holes.indexOf("DEF") >= 0) optional.push("Team defense to No DEF");
      return { kind: "structural", season, from,
        summary: "Your roster has nobody left to start at " + slotWords(holes) + ", so " +
          (one ? "that spot is" : "those spots are") + " empty every week, byes or not. " +
          (one ? "Add one" : "Add players for them") +
          (optional.length ? ", or set " + joinWords(optional) + " above." : ".") };
    }
    const weeks = [];
    for (let w = from; w <= through; w++) weeks.push(w);
    const hits = byeCollisions(roster, slots, weeks);
    const hitOf = new Map(hits.map((h) => [h.week, h]));
    const thin = thinSlots(roster, slots);
    const byeTeams = new Map(byes.weeks.map((w) => [w.week, w.bye]));
    const rows = weeks.map((week) => {
      const tag = week === TITLE_WEEK ? "Title game*"
                : PLAYOFF_WEEKS.indexOf(week) >= 0 ? "Fantasy playoffs*" : "";
      const hit = hitOf.get(week);
      const idle = roster.filter((r) => r.bye === week).map((r) => r.name).sort(byCodePoint);
      const base = { week, head: "Week " + week, now: week === current,
                     tag, playoff: tag !== "" };
      if (hit) {
        const out = hit.out.length ? " " + joinWords(hit.out) + " can't cover." : "";
        return Object.assign(base, { kind: "empty",
          chip: slotWords(hit.slots) + (hit.slots.length === 1 ? " spot empty" : " spots empty"),
          detail: "On bye: " + joinWords(hit.short) + ". Nobody else on your roster can " +
            "start there." + out });
      }
      if (idle.length) {
        // With a thin spot on the roster "each spot" would include one that is
        // empty every week anyway; the bye itself opens nothing new.
        return Object.assign(base, { kind: "covered", chip: "Covered",
          detail: "On bye: " + joinWords(idle) + ". " + (thin.length
            ? "Each of them can be covered from your roster."
            : "Someone else on your roster can start in each spot.") });
      }
      return Object.assign(base, { kind: "idle", chip: "",
        detail: "Nobody on your roster is on bye." });
    });
    const anyByes = weeks.some((w) => (byeTeams.get(w) || []).length);
    const ahead = roster.some((r) => r.bye !== null && r.bye >= from && r.bye <= through);
    const holeWeeks = hits.map((h) => h.week);
    let summary;
    if (!anyByes) {
      summary = "No NFL team has a bye from Week " + from + " through Week " + through +
        " — nothing to plan around.";
    } else if (holeWeeks.length) {
      const n = holeWeeks.length;
      summary = n + (n === 1 ? " week leaves" : " weeks leave") + " a starting spot empty: " +
        weekList(holeWeeks) + ".";
    } else {
      summary = "No week from " + from + " through " + through + " leaves a starting " +
        "spot empty. " + (ahead ? "Every bye on your roster is covered."
                                : "Nobody on your roster has a bye left.");
    }
    const playoffsShown = weeks.some((w) => PLAYOFF_WEEKS.indexOf(w) >= 0);
    const playoffByes = PLAYOFF_WEEKS.some((w) => (byeTeams.get(w) || []).length);
    const thinNames = outNames(roster, thin, new Set());
    const asOf = etDay(byes.generated);
    return {
      kind: "plan", season, from, through, holes: holeWeeks, summary,
      head: "3 · Your byes, Week " + from + " to Week " + through,
      thin: thin.length ? "Every week, byes or not: nobody can start at " + slotWords(thin) +
        (thinNames.length ? " — " + joinWords(thinNames) + " can't play." : ".") : "",
      weeks: rows,
      playoffNone: playoffsShown && !playoffByes ? "No NFL team has a bye in Weeks 15–17." : "",
      footnote: playoffsShown ? FOOTNOTE : "",
      asOf: "Reserve-list status as of " + (asOf || "the latest update") + " (nflverse): a " +
        "player on injured reserve, the PUP or non-football injury list, suspended or " +
        "released isn't counted as cover.",
    };
  }

  const B = { byeCollisions, unfillableSlots, thinSlots, structural, FLEX_ELIGIBILITY,
              slotWords, joinWords, currentWeek, rosterRows, rowMeta, describe, etDay };
  if (typeof module !== "undefined" && module.exports) module.exports = B;
  else globalThis.B = B;
})();
