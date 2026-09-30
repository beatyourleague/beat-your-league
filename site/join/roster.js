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
// Mirrors engine/roster.py TEAM_ALIASES: the league apps' spellings of teams
// whose nflverse code differs ("LAR" for the Rams). Stripped like a team code,
// and accepted as a defense on their own.
const TEAM_ALIASES = {LAR: "LA", WSH: "WAS", JAC: "JAX", LVR: "LV", ARZ: "ARI",
  GNB: "GB", KAN: "KC", NOR: "NO", NWE: "NE", SFO: "SF", TAM: "TB", HST: "HOU",
  BLT: "BAL", CLV: "CLE"};

// "Bench", "Starters", "Reserve(s)": section headers a copied roster carries.
// Also stripped (a battery of Yahoo / CBS / NFL.com / Sleeper / ESPN pastes):
// multi-position slot labels, injury and status tags, matchup and kickoff
// text. Mirrors engine/roster.py _DECORATION exactly.
const DECORATION =
  /\b(?:W\/R\/T|R\/W\/T|W\/R|W\/T|OP)\b|\b(?:QB|RB|WR|TE|FB|DEF|DST|D\/ST|FLEX|BN|BE|IR|TAXI|SUPER_FLEX|SFLEX|BENCH|STARTERS?|RESERVES?|OUT|DTD|SSPD|SUSP|PUP|NFI|INJ|NA|AM|PM)\b|\bVS\.?(?=\s|$)|\b(?:MON|TUE|WED|THU|FRI|SAT|SUN)\b.*$|\bBYE\b.*$|\([^)]*\)|\[[^\]]*\]|[-–—•|,:*@+]+|\d+(?:\.\d+)?/gi;
const POSITION_TAG = /\b(?:QB|RB|WR|TE|FB|K)\b/i;
const DEFENSE_TAG = /\b(?:DEF|DST|D\/ST)\b/i;
// A lone team code beside any of these is an OPPONENT or a note, never a
// roster entry ("vs. MIA", "BUF (Bye 7)", "Buf - Q"). Mirrors engine/roster.py.
const NOISE = /\bVS\b|@|\bBYE\b|\b(?:MON|TUE|WED|THU|FRI|SAT|SUN)\b|\b(?:OUT|DTD|SSPD|SUSP|PUP|NFI|INJ|NA)\b|\d/i;
// Whitespace the two languages disagree about is a plain space in both.
const WHITESPACE = /[\s\u0085\u001c-\u001f\u00a0\u2028\u2029\ufeff]+/g;

function tidy(line) {
  return (line || "").replace(WHITESPACE, " ").trim();
}

// Nothing to resolve: no LETTER of any script survives (emoji and bullets are
// blank; a line of Cyrillic is not — it is reported back).
function isBlank(cleaned) {
  return !/\p{L}/u.test(cleaned || "");
}

function stripDecoration(line, teams, keepLead) {
  const raw = tidy(line);
  let text = raw.replace(DECORATION, " ").replace(/\s+/g, " ").trim();
  // A NON-LEADING bare K is the kicker position tag ("Jake Bates K DET");
  // a leading K is an initial ("K. Walker", "K Walker") and stays.
  text = text.replace(/(?<=[^\s.]) K(?= |$)/gi, "").trim();
  // Single-letter injury tags (Q, O, D, P) trail a name or stand alone; a lone
  // "K" is a kicker slot header. An initial leads a name and carries its dot.
  const before = text ? text.split(" ") : [];
  let tokens = before.filter((t, i) => !(/^[QODPqodp]$/.test(t) && (i > 0 || before.length === 1)));
  const removedTag = tokens.length !== before.length;
  if (tokens.length === 1 && tokens[0].toUpperCase() === "K") tokens = [];
  text = tokens.join(" ");
  if (teams && teams.size) {
    const isTeam = (w) => teams.has(w.toUpperCase()) || (w.toUpperCase() in TEAM_ALIASES);
    // A team code beside a position tag, or beside matchup / bye / status /
    // projection text, is a PLAYER's line or a note, not a defense; a defense
    // carries DEF/DST/D/ST or stands alone.
    if (tokens.length === 1 && isTeam(tokens[0]) && !DEFENSE_TAG.test(raw) &&
        (POSITION_TAG.test(raw) || NOISE.test(raw) || removedTag)) {
      return "";
    }
    // keepLead keeps a team code that LEADS the line: "KC Concepcion WR CLE" is
    // a player named KC, and stripping both codes leaves "Concepcion".
    const kept = text.split(" ").filter((w, i) => !(isTeam(w) && !(keepLead && i === 0)));
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
        .concat(Object.keys(TEAM_ALIASES).filter((a) => TEAM_ALIASES[a] === team))
        .forEach((form) => push(normalize(form)));
    }
  }
  // (first initial, normalised surname) -> players: "J. Mixon". A unique match
  // is a lookup, two are a choice (RULE R3). Mirrors PlayerDirectory._by_initial.
  const byInitial = new Map();
  for (const [name, id, position, team] of payload.players) {
    if (position === "DEF") continue;
    const at = name.trim().indexOf(" ");
    if (at < 0) continue;
    const key = name.trim()[0].toLowerCase() + "|" + normalize(name.trim().slice(at + 1));
    if (key.endsWith("|")) continue;
    if (!byInitial.has(key)) byInitial.set(key, []);
    byInitial.get(key).push(byId.get(id));
  }
  // What may follow a comma as a team ANNOTATION on a player's line: a full team
  // name or a code. A bare nickname ("Josh Allen, Ravens") is a second roster
  // entry and must not be swallowed. Mirrors PlayerDirectory._team_annotation_keys.
  const teamKeys = new Set();
  for (const [name, id, position, team] of payload.players) {
    if (position !== "DEF" || !team) continue;
    teamKeys.add(normalize(name));
    teamKeys.add(normalize(team));
    Object.keys(TEAM_ALIASES).filter((a) => TEAM_ALIASES[a] === team)
      .forEach((a) => teamKeys.add(normalize(a)));
  }
  const confusable = new Map();
  for (const [a, b] of payload.confusable || []) {
    if (!confusable.has(a)) confusable.set(a, []);
    if (!confusable.has(b)) confusable.set(b, []);
    confusable.get(a).push(b);
    confusable.get(b).push(a);
  }
  return { byName, byId, byInitial, teamKeys, teams, confusable, season: payload.season };
}

// ---------------------------------------------------------------- //
// resolution — RULE R3: ambiguity is RETURNED, never resolved
// ---------------------------------------------------------------- //

// Shapes beyond a plain name — "Last, First", "Name, Team Name" (a FULL team
// name or code after the comma; a bare nickname is a second roster entry), a
// leading team code that is really part of a name ("KC Concepcion"), NFL.com's
// leading "K Jake Bates" and "J. Mixon" — are lookups that must come back
// unique, tried only after the plain reading fails, so nothing that resolved
// before resolves differently. Mirrors PlayerDirectory.resolve.
function resolveLine(directory, typed) {
  typed = tidy(typed);
  const first = resolvePlain(directory, typed, false);
  if (first.player || first.candidates.length) return first;
  const ok = (player) => ({ typed, player, candidates: [], twins: [] });
  if (typed.includes(",")) {
    const at = typed.indexOf(",");
    const a = stripDecoration(typed.slice(0, at), directory.teams);
    const b = stripDecoration(typed.slice(at + 1), directory.teams);
    if (a && b) {
      if (directory.teamKeys.has(normalize(b))) {
        const retry = resolvePlain(directory, typed.slice(0, at), false);
        if (retry.player) return ok(retry.player);
      }
      const found = directory.byName.get(normalize(b + " " + a)) || [];
      if (found.length === 1) return ok(found[0]);
    }
  }
  // A team code that leads a NAME is stripped as decoration by the plain
  // reading; keep the lead and try once more.
  const lead = resolvePlain(directory, typed, true);
  if (lead.player) return lead;
  const cleaned = stripDecoration(typed, directory.teams);
  const tag = /^K\s+(\S+\s+\S.*)$/.exec(cleaned);
  if (tag) {
    const found = directory.byName.get(normalize(tag[1])) || [];
    if (found.length === 1) return ok(found[0]);
  }
  const init = /^([A-Za-z])\.?\s+(.+)$/.exec(cleaned);
  if (init) {
    const found = directory.byInitial.get(init[1].toLowerCase() + "|" + normalize(init[2])) || [];
    if (found.length === 1) return ok(found[0]);
    if (found.length) return { typed, player: null, candidates: found, reason: "ambiguous" };
  }
  return first;
}

function resolvePlain(directory, typed, keepLead) {
  const cleaned = stripDecoration(typed, directory.teams, keepLead);
  // Blank means no LETTER survives; letters of any script are reported back.
  if (isBlank(cleaned)) return { typed, player: null, candidates: [], reason: "blank" };
  const key = normalize(cleaned);
  if (!key) return { typed, player: null, candidates: [], reason: "unknown" };
  // Defense aliases and display names are ONE pool (byName holds both), so an
  // alias colliding with a player's name comes back as a choice, never a pick.
  const found = [...new Map((directory.byName.get(key) || []).map((p) => [p.id, p])).values()];
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

// One pasted row -> a match. A desktop copy of a roster table arrives
// tab-separated, and the name is one cell among several ("Josh Allen QB BUF
// vs. Miami Dolphins ..."). The longest cell used to win, which turned an
// OPPONENT cell into a phantom defense and silently dropped the player. Every
// cell is resolved; a player beats a defense (the defense cell is the player's
// team or opponent), and the longest resolved cell breaks a tie. Mirrors
// PlayerDirectory._resolve_row.
function resolveRow(directory, line) {
  const cells = line.split("\t").map((c) => c.trim()).filter(Boolean);
  if (cells.length <= 1) return resolveLine(directory, cells[0] || line.trim());
  const results = cells.map((cell) => [cell, resolveLine(directory, cell)])
    .filter(([, match]) => match.reason !== "blank");
  if (!results.length) return { typed: line, player: null, candidates: [], reason: "blank" };
  const resolved = results.filter(([, m]) => m.player);
  const players = resolved.filter(([, m]) => m.player.position !== "DEF");
  const pool = players.length ? players : resolved.length ? resolved : results;
  return pool.reduce((best, cur) => (cur[0].length > best[0].length ? cur : best))[1];
}

function resolveAll(directory, text) {
  return (text || "")
    .split(/[\r\n]+/)
    .map((line) => line.trim())
    // Blank lines are dropped; anything with LETTERS is REPORTED BACK, even if
    // unreadable. Pasting fifteen and silently getting thirteen is the same
    // failure as guessing, wearing a different hat.
    .filter((line) => line.length > 0)
    .map((line) => resolveRow(directory, line))
    .filter((match) => match.reason !== "blank")
    // The same player on consecutive lines is one entry: Yahoo prints a
    // defense's name and then its "Den - DEF" row.
    .filter((match, i, all) => !(match.player && i > 0 && all[i - 1].player &&
                                 all[i - 1].player.id === match.player.id));
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
