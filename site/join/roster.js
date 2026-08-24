"use strict";
// Name resolution and signup encoding, in the browser.
//
// THIS FILE IS HALF OF A CONTRACT WITH NOTHING TYPE-CHECKING ACROSS IT. The
// other half is engine/roster.py (normalisation, the ambiguity rule) and
// run/refs.py (the packed reference). If the two disagree, a subscriber pays
// and Tuesday cannot decode what they bought — or worse, decodes it as somebody
// else's roster. tests/test_intake.py runs this file under node against the
// Python implementations on the same inputs, which is the only thing that keeps
// them honest.
//
// Why resolution happens HERE rather than on Tuesday: ambiguity can only be
// settled by the person who knows the answer (RULE R3), and on Tuesday there is
// nobody to ask. A cron that guesses produces a confident report about a player
// the subscriber does not own.

// ---------------------------------------------------------------- //
// normalisation — mirrors engine/roster.py normalize()
// ---------------------------------------------------------------- //

// Order matters and is the same in both languages: accents fold before the
// alphabetic filter (so "José" becomes "jose", not "jos"), and suffixes are
// stripped before punctuation (so "Jr." is caught while it still has its dot).
const SUFFIX = /\b(jr|sr|ii|iii|iv|v)\b\.?/g;

function normalize(name) {
  // NFKD then drop combining marks: the JS twin of Python's unicodedata dance.
  let s = (name || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  s = s.replace(SUFFIX, " ");
  // Letters only, spaces included — "JAMARR CHASE" must reach "Ja'Marr Chase",
  // and people do not reproduce apostrophes. Measured safe: zero collisions in
  // the eligible pool.
  return s.replace(/[^a-z]/g, "");
}

// Decoration a pasted roster carries. "K" is deliberately absent: it would eat
// the K of "K. Walker", and a kicker's line is identifiable without it.
const DECORATION =
  /\b(?:QB|RB|WR|TE|DEF|DST|D\/ST|FLEX|BN|BE|IR|TAXI|SUPER_FLEX|SFLEX)\b|\bBYE\b.*$|\([^)]*\)|\[[^\]]*\]|[-–—•|,]+|\d+(?:\.\d+)?/gi;

function stripDecoration(line, teams) {
  let text = (line || "").replace(DECORATION, " ").replace(/\s+/g, " ").trim();
  // A NON-LEADING bare K is the kicker position tag ("Jake Bates K DET");
  // a leading K is an initial ("K. Walker", "K Walker") and stays.
  text = text.replace(/(?<=[^\s.]) K(?= |$)/gi, "").trim();
  if (teams && teams.size) {
    const kept = text.split(" ").filter((w) => !teams.has(w.toUpperCase()));
    // Only if something survives: "KC" alone IS the Chiefs defense, while the
    // same token inside "Mahomes QB KC" is noise.
    if (kept.length) text = kept.join(" ");
  }
  return text;
}

// ---------------------------------------------------------------- //
// the directory
// ---------------------------------------------------------------- //

function buildDirectory(payload) {
  const byName = new Map();
  const byId = new Map();
  const teams = new Set();
  for (const [name, id, position, team] of payload.players) {
    const player = { name, id, position, team };
    byId.set(id, player);
    if (team) teams.add(team.toUpperCase());
    const push = (key) => {
      if (!key) return;
      if (!byName.has(key)) byName.set(key, []);
      byName.get(key).push(player);
    };
    push(normalize(name));
    if (position === "DEF" && team) {
      // A manager writes a defense a dozen ways and none of them is anybody's
      // display name.
      const parts = name.split(" ");
      const nick = parts[parts.length - 1];
      const city = parts.slice(0, -1).join(" ");
      [team, nick, city, team + " DEF", nick + " DEF", name + " DEF"]
        .forEach((form) => push(normalize(form)));
    }
  }
  const confusable = new Map();
  for (const [a, b] of payload.confusable || []) {
    if (!confusable.has(a)) confusable.set(a, []);
    if (!confusable.has(b)) confusable.set(b, []);
    confusable.get(a).push(b);
    confusable.get(b).push(a);
  }
  return { byName, byId, teams, confusable, season: payload.season };
}

// ---------------------------------------------------------------- //
// resolution — RULE R3: ambiguity is RETURNED, never resolved
// ---------------------------------------------------------------- //

function resolveLine(directory, typed) {
  const cleaned = stripDecoration(typed, directory.teams);
  const key = normalize(cleaned);
  if (!key) return { typed, player: null, candidates: [], reason: "blank" };
  const found = directory.byName.get(key) || [];
  if (found.length === 1) {
    const player = found[0];
    return {
      typed,
      player,
      candidates: [],
      // Not an error — a nudge shown inline. Bijan Robinson and Brian Robinson
      // are the same position on the same team, which is the one pair a confirm
      // row cannot separate on sight.
      twins: (directory.confusable.get(player.id) || [])
        .map((id) => directory.byId.get(id))
        .filter(Boolean),
    };
  }
  if (found.length > 1) {
    return { typed, player: null, candidates: found, reason: "ambiguous" };
  }
  return { typed, player: null, candidates: [], reason: "unknown" };
}

function resolveAll(directory, text) {
  // Split on newlines AND tabs: a desktop copy of a roster table arrives
  // tab-separated, and treating the whole row as one name fails every time.
  return (text || "")
    .split(/[\r\n]+/)
    .map((line) => line.split("\t").map((c) => c.trim()).filter(Boolean).sort(
      (a, b) => b.length - a.length)[0] || line)
    .map((line) => line.trim())
    // Blank lines are dropped; anything with characters is REPORTED BACK, even
    // if unreadable. Pasting fifteen and silently getting thirteen is the same
    // failure as guessing, wearing a different hat.
    .filter((line) => line.length > 0)
    .map((line) => resolveLine(directory, line))
    .filter((match) => match.reason !== "blank");
}

// ---------------------------------------------------------------- //
// the signup reference — mirrors run/refs.py encode_roster
// ---------------------------------------------------------------- //

const SCORING_CODE = { ppr: "p", half_ppr: "h", standard: "s" };
const SLOT_CODE = { QB: "Q", RB: "R", WR: "W", TE: "T", FLEX: "F", K: "K",
                    DEF: "D", SUPER_FLEX: "S" };
const DEFENSE_FLAG = 0xff0000;
const MAX_ROSTER = 30;
const REF_RE = /^[A-Za-z0-9_-]{1,200}$/;

function packOne(playerId) {
  if (playerId.startsWith("DEF-")) {
    const abbr = playerId.slice(4).toUpperCase();
    if (!/^[A-Z]{2,3}$/.test(abbr)) throw new Error("bad defense id " + playerId);
    let value = 0;
    for (let i = 0; i < 3; i++) {
      const code = i < abbr.length ? abbr.charCodeAt(i) - 64 : 0;
      value = (value << 5) | code;
    }
    return DEFENSE_FLAG | value;
  }
  if (!/^00-\d{7}$/.test(playerId)) throw new Error("not a GSIS id " + playerId);
  return parseInt(playerId.slice(3), 10);
}

function base64url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// v3 adds the league SIZE at a fixed position. It must match run/refs.py
// exactly — the two are a contract with nothing type-checking across it, and
// test_the_browser_and_python_agree_on_the_format pins this literal source.
const SIZE_CODE = { 8: "a", 10: "b", 12: "c", 14: "d" };

function encodeRoster(plan, scoring, slots, playerIds, leagueSize) {
  const prefix = { season: "s", monthly: "m", league_pass: "p" }[plan];
  if (!prefix) throw new Error("unknown plan " + plan);
  const scoringCode = SCORING_CODE[scoring];
  if (!scoringCode) throw new Error("unknown scoring " + scoring);
  const sizeCode = SIZE_CODE[leagueSize === undefined ? 12 : leagueSize];
  if (!sizeCode) throw new Error("unsupported league size " + leagueSize);
  if (!slots.length) throw new Error("a ref needs at least one starting slot");
  if (!playerIds.length) throw new Error("a ref needs at least one player");
  if (playerIds.length > MAX_ROSTER) throw new Error("roster too long");
  if (new Set(playerIds).size !== playerIds.length) {
    throw new Error("the same player appears twice in this roster");
  }
  let slotCodes = "";
  for (const slot of slots) {
    const code = SLOT_CODE[slot];
    if (!code) throw new Error("unknown slot " + slot);
    slotCodes += code;
  }
  if (playerIds.length < slotCodes.length) {
    throw new Error(slotCodes.length + " starting slots but only " +
                    playerIds.length + " players");
  }
  const bytes = [];
  for (const id of playerIds) {
    const value = packOne(id);
    bytes.push((value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff);
  }
  const ref = prefix + "3-" + scoringCode + sizeCode + slotCodes + "-" +
              base64url(bytes);
  // Stripe SILENTLY drops an invalid client_reference_id while still showing a
  // working payment page, so this is the only place the failure can be made
  // loud. Asserted before anything navigates.
  if (!REF_RE.test(ref)) throw new Error("encoded ref is not Stripe-safe");
  return ref;
}

// Exposed under ONE name in both worlds. In node the tests require() it; in a
// browser there is no module system here, so the page needs a global — and the
// page must not re-declare any of these names, because a plain <script> shares
// the global scope and a second `const REF_RE` is a SyntaxError that kills the
// whole file silently from the page's point of view.
const R = { normalize, stripDecoration, buildDirectory, resolveLine, resolveAll,
            encodeRoster, packOne, REF_RE, MAX_ROSTER, SIZE_CODE };
if (typeof module !== "undefined" && module.exports) {
  module.exports = R;
} else {
  globalThis.R = R;
}
