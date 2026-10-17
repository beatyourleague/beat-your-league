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
// ESPN's table headings and totals row ("SLOT", "OPRK", "%ROST", "TOTALS",
// "7th") ride along with a copied roster (BE-D1); a bare ST is the St. of
// Amon-Ra St. Brown, so "%ST" goes only with its percent sign.
const DECORATION =
  /\b(?:W\/R\/T|R\/W\/T|W\/R|W\/T|OP)\b|\b(?:QB|RB|WR|TE|FB|DEF|DST|D\/ST|FLEX|BN|BE|IR|TAXI|SUPER_FLEX|SFLEX|BENCH|STARTERS?|RESERVES?|OUT|DTD|SSPD|SUSP|PUP|NFI|INJ|NA|AM|PM)\b|\b(?:SLOT|PLAYERS?|OPP|STATUS|PROJ|SCORE|OPRK|PRK|FPTS|AVG|LAST|TOTALS?|NFL|WEEK|SEASON)\b|%\s*(?:ST|ROST)\b|\b\d+(?:ST|ND|RD|TH)\b|\bVS\.?(?=\s|$)|\b(?:MON|TUE|WED|THU|FRI|SAT|SUN)\b.*$|\bBYE\b.*$|\([^)]*\)|\[[^\]]*\]|[-–—•|,:*@+%]+|\d+(?:\.\d+)?/gi;
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

// Tags a table copy glues onto the cell before them (BE-D1, a real ESPN
// copy): "PhiQB", "Jalen HurtsQ", "Eagles D/STD/ST". Narrow on purpose so no
// real name splits: a tag run after a LOWERCASE letter, a tag run after a real
// team code, or a doubled defense tag. Mirrors engine/roster.py _unglue.
const GLUE_TAG = "(?:D/ST|DST|DEF|SSPD|SUSP|DTD|OUT|PUP|NFI|IR|QB|RB|WR|TE|FB|K|Q|O|D|P)";
const GLUED_TO_NAME = new RegExp("^([A-Za-z.'-]*[a-z.'])((?:" + GLUE_TAG + ")+)$");
const GLUED_CODE = new RegExp("^([A-Z]{2,3})((?:" + GLUE_TAG + ")+)$");
const DOUBLED_DEFENSE = /^(?:D\/ST|DST|DEF){2,}$/;
const ONE_TAG = new RegExp(GLUE_TAG, "g");

function unglue(raw, teams) {
  const words = [];
  for (const word of raw.split(" ")) {
    const glued = GLUED_TO_NAME.exec(word);
    // A token that IS a team code is never split: "SFO" is San Francisco, not
    // SF plus an "O" (out) tag.
    const isCode = Boolean(teams) && (teams.has(word.toUpperCase()) || word.toUpperCase() in TEAM_ALIASES);
    const coded = isCode ? null : GLUED_CODE.exec(word);
    if (DOUBLED_DEFENSE.test(word)) {
      words.push(...word.match(ONE_TAG));
    } else if (glued) {
      words.push(glued[1], ...glued[2].match(ONE_TAG));
    } else if (coded && teams && (teams.has(coded[1]) || coded[1] in TEAM_ALIASES)) {
      words.push(coded[1], ...coded[2].match(ONE_TAG));
    } else {
      words.push(word);
    }
  }
  return words.join(" ");
}

const POSITION_WORDS = new Set(["QB", "RB", "WR", "TE", "K", "FB", "DEF", "DST"]);
const PLAYER_POSITIONS = new Set(["QB", "RB", "WR", "TE", "K", "FB"]);

// The position tags a line holds when it holds NOTHING else ("QB", "D/ST") —
// the third cell of a table copy's player block. Mirrors _position_line.
function positionLine(line, teams) {
  const raw = unglue(tidy(line || ""), teams).toUpperCase().replace(/D\/ST/g, "DST");
  const words = raw.split(/[\s/,]+/).filter(Boolean);
  return words.length && words.every((w) => POSITION_WORDS.has(w)) ? new Set(words) : new Set();
}

// Is this position line the entry's OWN position? Mirrors _plays.
function plays(player, tags) {
  if (!player) return [...tags].some((t) => PLAYER_POSITIONS.has(t));
  if (player.position === "DEF") return tags.has("DEF") || tags.has("DST");
  return tags.has(player.position) || (player.position === "FB" && tags.has("RB"));
}

function canonical(team) {
  const t = (team || "").toUpperCase();
  return TEAM_ALIASES[t] || t || null;
}

// Is what was typed this player's FULL name, letter for letter (case and
// spacing aside)? I15: an exact "Bijan Robinson" no longer offers "not Brian
// Robinson? tap to swap". Mirrors engine/roster.py exact_name.
function exactName(typed, name, teams) {
  return sameName(stripDecoration(typed, teams), name);
}
function sameName(cleaned, name) {
  const fold = (text) => (text || "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
  return fold(cleaned) === fold(name);
}

function stripDecoration(line, teams, keepLead) {
  const raw = unglue(tidy(line), teams);
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
    // Every word a team code counts the same way: "PhiQB CAR Sun 1:00 PM" is a
    // player's team and his opponent (BE-D1), not two defenses.
    if (tokens.length && tokens.every(isTeam) && !DEFENSE_TAG.test(raw) &&
        (POSITION_TAG.test(raw) || NOISE.test(raw) || removedTag)) {
      return "";
    }
    // keepLead keeps a team code that LEADS the line: "KC Concepcion WR CLE" is
    // a player named KC, and stripping both codes leaves "Concepcion".
    const kept = text.split(" ").filter((w, i) => !(isTeam(w) && !(keepLead && i === 0)));
    // A bare K left once a team code is gone is a kicker's TEAM line, laid out
    // position-first the way Sleeper writes it ("K - PIT", "K DAL"). Only when
    // a team code was actually stripped. Mirrors engine/roster.py.
    if (kept.length < tokens.length && kept.length === 1 && kept[0].toUpperCase() === "K") {
      return "";
    }
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
  // A fifth field, when present, is the typeahead's sort key (PPR points
  // across last season and this one; render/player_index.py). An older
  // four-field payload still loads: the key is simply unknown.
  for (const [name, id, position, team, points] of payload.players) {
    const player = { name, id, position, team,
                     relevance: typeof points === "number" ? points : null };
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
  // Part of a name, typed on its own: "Hurts", "St. Brown", "Puka". A lookup
  // of last resort whose answer is ALWAYS a choice, even when one player fits
  // (RULE R3). Mirrors PlayerDirectory._by_part.
  const byPart = new Map();
  for (const player of byId.values()) {
    if (player.position === "DEF") continue;
    for (const key of namePartKeys(player.name)) {
      if (!byPart.has(key)) byPart.set(key, []);
      byPart.get(key).push(player);
    }
  }
  const confusable = new Map();
  for (const [a, b] of payload.confusable || []) {
    if (!confusable.has(a)) confusable.set(a, []);
    if (!confusable.has(b)) confusable.set(b, []);
    confusable.get(a).push(b);
    confusable.get(b).push(a);
  }
  return { byName, byId, byInitial, byPart, teamKeys, teams, confusable,
           season: payload.season };
}

// The parts of a name a manager types on its own (FUNNEL F9, BE2-D2: a pasted
// "Hurts", "Kelce" or "Butker" read "we don't have anybody by that name" while
// the typeahead on the same page listed him): the first name, and every tail
// of the name — "Brown" and "St. Brown" from "Amon-Ra St. Brown", "Njigba"
// and "Smith-Njigba", "Walker" from "Kenneth Walker III" (the suffix folds
// away). Under three letters is too little to go on ("A.J.", "Bo").
// Mirrors engine/roster.py _name_part_keys.
function namePartKeys(name) {
  const words = (name || "").trim().split(/[\s-]+/).filter(Boolean);
  if (words.length < 2) return [];
  const keys = new Set([normalize(words[0])]);
  for (let i = 1; i < words.length; i++) keys.add(normalize(words.slice(i).join(" ")));
  return [...keys].filter((key) => key.length >= 3);
}

// How many players a part-name choice offers: the typeahead's eight, ranked
// the typeahead's way, so a pasted "Williams" offers the list that typing it
// into "Add a player" shows first.
const PART_CHOICES = 8;

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
  // Last: part of a name. Never a pick, even when one player fits — a pasted
  // "Allen" with one Allen in the directory is still a guess at which Allen,
  // and the person typing is the one who knows (RULE R3).
  const part = normalize(cleaned);
  const fits = part.length >= 3 && directory.byPart ? directory.byPart.get(part) || [] : [];
  if (fits.length) {
    return { typed, player: null, reason: "partial",
             candidates: [...fits].sort(byRelevance).slice(0, PART_CHOICES) };
  }
  return first;
}

// Not an error — a nudge shown inline. Bijan Robinson and Brian Robinson are
// the same position on the same team, which is the one pair a confirm row
// cannot separate on sight.
function twinsOf(directory, player) {
  return (directory.confusable.get(player.id) || [])
    .map((id) => directory.byId.get(id))
    .filter(Boolean);
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
    // A near-name alternate only when the name was NOT typed out in full: an
    // exact "Bijan Robinson" offering "not Brian Robinson?" read as doubt
    // about a household name (I15).
    return { typed, player, candidates: [],
             twins: sameName(cleaned, player.name) ? [] : twinsOf(directory, player) };
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
  // BE-D1: "PhiQB<tab>CAR<tab>Sun 1:00 PM" — a player's team-and-position
  // cell, his opponent's code, his kickoff — read as the Panthers defense.
  // When nothing but bare codes resolved, the row is judged whole, the way a
  // one-line row is. Mirrors PlayerDirectory._resolve_row.
  if (!players.length && resolved.length &&
      resolved.every(([cell]) => codeOnly(directory, cell)) &&
      isBlank(stripDecoration(cells.join(" "), directory.teams))) {
    return { typed: line, player: null, candidates: [], reason: "blank" };
  }
  const pool = players.length ? players : resolved.length ? resolved : results;
  return pool.reduce((best, cur) => (cur[0].length > best[0].length ? cur : best))[1];
}

// The team (nflverse code) when a row reads as a defense ONLY because it is a
// bare team code with no DEF tag anywhere on it; otherwise null. Those are the
// rows a table copy makes out of a player's team or opponent column, so they
// are the only ones read in context. Mirrors PlayerDirectory._code_only.
function codeOnly(directory, line) {
  const cells = line.split("\t").map((c) => c.trim()).filter(Boolean);
  const raw = unglue(tidy(cells.join(" ")), directory.teams);
  if (DEFENSE_TAG.test(raw)) return null;
  const tokens = stripDecoration(cells.join(" "), directory.teams).split(" ").filter(Boolean);
  if (tokens.length !== 1) return null;
  const word = tokens[0].toUpperCase();
  if (!directory.teams.has(word) && !(word in TEAM_ALIASES)) return null;
  return TEAM_ALIASES[word] || word;
}

// Every non-blank line, in order — mirrors PlayerDirectory.resolve_all,
// including how a bare team code is read IN CONTEXT (BE-D1): ESPN's table
// copies "Jalen Hurts / Phi / QB / CAR" one cell per line, and every code line
// became a defense — eleven for a roster that owned one, under "Looks right".
// After an entry, a bare code is his TEAM line (his team, or the next line is
// a position tag) and, once his own position line is read, his OPPONENT.
function resolveAll(directory, text) {
  const lines = (text || "").split(/[\r\n]+/).map((line) => line.trim())
    // Blank lines are dropped; anything with LETTERS is REPORTED BACK, even if
    // unreadable. Pasting fifteen and silently getting thirteen is the same
    // failure as guessing, wearing a different hat.
    .filter((line) => line.length > 0);
  const out = [];
  let block = null;           // what has been read since the last entry
  lines.forEach((line, index) => {
    const match = resolveRow(directory, line);
    if (match.reason === "blank") {
      const tags = positionLine(line, directory.teams);
      if (block && tags.size && plays(out[out.length - 1].player, tags)) block.position = true;
      return;
    }
    const code = codeOnly(directory, line);
    if (code && block) {
      const last = out[out.length - 1].player;
      if (!block.team && !block.position &&
          ((last && canonical(last.team) === code) ||
           (index + 1 < lines.length && positionLine(lines[index + 1], directory.teams).size))) {
        block.team = true;
        return;
      }
      if (block.position) return;
    }
    // The same player on consecutive lines is one entry: Yahoo prints a
    // defense's name and then its "Den - DEF" row.
    const prev = out[out.length - 1];
    if (match.player && prev && prev.player && prev.player.id === match.player.id) return;
    out.push(match);
    block = { team: false, position: false };
  });
  return out;
}

// ---------------------------------------------------------------- //
// type-to-add suggestions
// ---------------------------------------------------------------- //

// Where a typed query may begin inside a name: the start of each word,
// hyphenated halves included, so "Brown" finds "Amon-Ra St. Brown" and
// "Njigba" finds "Jaxon Smith-Njigba" at a word start rather than mid-word.
function wordStarts(name) {
  const words = (name || "").split(/[\s-]+/).filter(Boolean);
  return words.map((_, i) => normalize(words.slice(i).join(" "))).filter(Boolean);
}

// Launch audit PC-09: the directory is alphabetical by FIRST name, so a
// surname search listed whoever came first ("Allen" put the quarterback
// everybody meant fourth) and Enter took the top one. Ranked now: the exact
// name, then a match at the start of a word (first name or surname), then one
// inside a word; within each, the player who has actually scored the most
// (relevance; unknown sorts last); then the name and id, so the order is the
// same on every visit. Ordering only — what can be added is unchanged.
function suggestPlayers(directory, query, limit) {
  const q = normalize(query);
  if (!directory || q.length < 2) return [];
  const ranked = [];
  for (const player of directory.byId.values()) {
    const full = normalize(player.name);
    const tier = full === q ? 0
               : wordStarts(player.name).some((key) => key.startsWith(q)) ? 1
               : full.includes(q) ? 2 : -1;
    if (tier >= 0) ranked.push({ tier, player });
  }
  ranked.sort((a, b) => (a.tier - b.tier) || byRelevance(a.player, b.player));
  return ranked.slice(0, limit || 8).map((entry) => entry.player);
}

// Who has actually scored the most first (unknown sorts last), then the name
// and the id, so the order is the same on every visit.
function byRelevance(a, b) {
  const points = (p) => (p.relevance === null || p.relevance === undefined
                         ? -Infinity : p.relevance);
  const pa = points(a), pb = points(b);
  if (pa !== pb) return pb > pa ? 1 : -1;
  if (a.name !== b.name) return a.name < b.name ? -1 : 1;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

// Enter adds a suggestion only when it cannot be the wrong one: the query IS a
// player's name, or exactly one suggestion is left. Otherwise null — Enter
// taking the top of a list the person has not read added players they never
// chose (PC-09).
function enterPick(suggested, query) {
  const q = normalize(query);
  const exact = suggested.find((player) => normalize(player.name) === q);
  if (exact) return exact;
  return suggested.length === 1 ? suggested[0] : null;
}

// A player tapped in the typeahead joins the list ALREADY ON SCREEN as one more
// row. The list carries decisions the paste box does not ("pick one" and
// "remove" change the list, never the text), so re-reading the box on every
// add silently undid them and blocked checkout again (launch audit F7). The
// tapped player IS the answer — no lookup by name, which could come back
// ambiguous for a name two players share. A new array: the old one is not
// touched. Browser-only (Python never sees an unencoded list). No near-name
// swap: the tapped row showed the full name, which is the exact-name case
// (I15) — the person read it and chose it.
function addPick(directory, matches, player) {
  return matches.concat([{ typed: player.name, player, candidates: [], twins: [] }]);
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
// v4 adds the ROSTER COUNT after the slots (two digits), so the end of the
// packed roster is known exactly and a trailing "_via-<tag>" can never be read
// off a payload that merely ends in those characters (base64url uses both "_"
// and "-"). Mirrors run/refs.py ROSTER_MARKER_V4 / split_via.
const VIA_SEPARATOR = "_via-";
const VIA_RE = /^[a-z0-9-]{1,24}$/;
const VIA_TAIL = /^(.+)_via-([a-z0-9-]{1,24})$/;
const V4_SETTINGS = /^([a-z])([a-z])([A-Z]+)(\d{2})$/;

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
  const count = String(playerIds.length).padStart(2, "0");
  const ref = prefix + "4-" + scoringCode + sizeCode + slotCodes + count + "-" +
              base64url(bytes);
  // Stripe SILENTLY drops an invalid client_reference_id while still showing a
  // working payment page, so this is the only place the failure can be made
  // loud. Asserted before anything navigates.
  if (!REF_RE.test(ref)) throw new Error("encoded ref is not Stripe-safe");
  return ref;
}

// (the ref without its source tag, the tag or null) — contract C5, by the one
// rule run/intake.split_via and run/refs.split_via apply: the tail comes off
// only when what is left is a whole, readable roster ref (for v4, exactly the
// count's 4 characters a player) — readable by decodeRoster itself, tag and
// all, so a ref tagged twice by hand splits at its last tag here too. Mirrors
// run/refs.py split_via.
function splitVia(ref) {
  if (typeof ref !== "string") return [ref, null];
  const m = VIA_TAIL.exec(ref);
  if (!m || !/^[a-z][234]-/.test(m[1])) return [ref, null];
  try {
    decodeRoster(m[1]);
  } catch (err) {
    return [ref, null];
  }
  return [m[1], m[2]];
}

// ``ref`` with "_via-<tag>" appended, or unchanged: an unusable tag is
// DROPPED, never refused (a purchase must never fail over attribution), and
// only a v4 ref knows where its payload ends. Mirrors run/refs.py with_via.
function withVia(ref, via) {
  if (!via || !VIA_RE.test(via) || typeof ref !== "string") return ref;
  if (!/^[smp]4-/.test(ref) || splitVia(ref)[1] !== null) return ref;
  const tagged = ref + VIA_SEPARATOR + via;
  return REF_RE.test(tagged) ? tagged : ref;
}

// split("-", 2) as Python means it: the payload is base64url and may hold "-".
function splitRef(ref) {
  const a = ref.indexOf("-");
  if (a < 0) return null;
  const b = ref.indexOf("-", a + 1);
  if (b < 0) return null;
  return [ref.slice(0, a), ref.slice(a + 1, b), ref.slice(b + 1)];
}

function unbase64url(text) {
  if (!/^[A-Za-z0-9_-]*$/.test(text)) throw new Error("unreadable roster");
  const padded = text.replace(/-/g, "+").replace(/_/g, "/") +
                 "=".repeat((4 - (text.length % 4)) % 4);
  const binary = atob(padded);
  return Array.from(binary, (c) => c.charCodeAt(0));
}

function unpackOne(value) {
  if ((value & DEFENSE_FLAG) === DEFENSE_FLAG) {
    let letters = "";
    for (const shift of [10, 5, 0]) {
      const code = (value >> shift) & 0x1f;
      if (code) letters += String.fromCharCode(code + 64);
    }
    if (!letters) throw new Error("defense entry carries no team");
    return "DEF-" + letters;
  }
  return "00-" + String(value).padStart(7, "0");
}

// The browser's reading of a ref — a waitlist launch email links back here
// with ?ref= (contract C6), and the page restores the roster and settings
// from it for checking. Every failure THROWS, like run/refs.py decode_roster:
// a partly-read roster restored as if whole is a roster the subscriber did
// not enter.
function decodeRoster(ref) {
  if (typeof ref !== "string" || !REF_RE.test(ref)) throw new Error("not a Stripe-safe reference");
  const [core, via] = splitVia(ref);
  return Object.assign(decodeCore(core), { via });
}

// A roster ref with no source tag on it -> the roster. Mirrors _decode_core.
function decodeCore(core) {
  const parts = splitRef(core);
  if (!parts) throw new Error("expected 3 fields");
  const [head, settings, packed] = parts;
  const plan = { s: "season", m: "monthly", p: "league_pass" }[head[0]];
  if (head.length !== 2 || !"234".includes(head[1]) || !plan) throw new Error("not a roster reference");
  const scoring = { p: "ppr", h: "half_ppr", s: "standard" }[settings[0]];
  if (!scoring) throw new Error("unknown scoring code");
  const sizes = { a: 8, b: 10, c: 12, d: 14 };
  let leagueSize = 12, slotCodes, count = null;
  if (head[1] === "4") {
    const m = V4_SETTINGS.exec(settings);
    if (!m || !(m[2] in sizes)) throw new Error("unreadable v4 settings");
    leagueSize = sizes[m[2]]; slotCodes = m[3]; count = Number(m[4]);
    if (packed.length !== 4 * count) throw new Error("the roster is not the players its count says");
  } else if (head[1] === "3") {
    if (!(settings[1] in sizes)) throw new Error("unknown league-size code");
    leagueSize = sizes[settings[1]]; slotCodes = settings.slice(2);
  } else {
    slotCodes = settings.slice(1);
  }
  const slotNames = {};
  Object.keys(SLOT_CODE).forEach((name) => { slotNames[SLOT_CODE[name]] = name; });
  if (!slotCodes || [...slotCodes].some((c) => !(c in slotNames))) throw new Error("bad slot template");
  const bytes = unbase64url(packed);
  if (!bytes.length || bytes.length % 3) throw new Error("roster is not a whole number of players");
  const n = bytes.length / 3;
  if (n > MAX_ROSTER) throw new Error("roster too long");
  const playerIds = [];
  for (let i = 0; i < n; i++) {
    playerIds.push(unpackOne((bytes[3 * i] << 16) | (bytes[3 * i + 1] << 8) | bytes[3 * i + 2]));
  }
  if (new Set(playerIds).size !== playerIds.length) throw new Error("the same player appears twice");
  if (n < slotCodes.length) throw new Error("more starting slots than players");
  return { plan, scoring, slots: [...slotCodes].map((c) => slotNames[c]), playerIds,
           leagueSize, via: null };
}

// ---------------------------------------------------------------- //
// lineup shapes — mirrors engine/subscriber.py LINEUP_SHAPES (contract C8)
// ---------------------------------------------------------------- //

// A shape is a BASE plus whether the league starts a kicker and a team
// defense, always in this order: base slots, then K, then DEF. Only the three
// graded shapes print odds; every other shape gets the lineup, projections
// and plans with the odds withheld until its own preregistered arm grades it.
const SHAPE_BASES = {
  std:   ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"],
  flex2: ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX"],
  wr3:   ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"],
  sf:    ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"],
};
// Graded by OFFENSE, the twin of engine.subscriber.graded_slots: a kicker or
// defense slot changes no other slot's call, so every K/DEF variant of a
// graded offense (standard, superflex) is graded too.
// Two FLEX and three WR graded B (reports/lineup-shapes-backtest.md, Oct 16 2026).
const GRADED_BASES = ["std", "sf", "flex2", "wr3"];

function shapeCode(base, kicker, defense) {
  if (!(base in SHAPE_BASES)) throw new Error("unknown lineup base " + base);
  const suffix = kicker && defense ? "" : kicker ? "-nod" : defense ? "-nok" : "-nokd";
  return base === "std" && suffix === "-nokd" ? "nokd" : base + suffix;
}

const GRADED_SHAPES = [];
for (const base of GRADED_BASES) {
  for (const kicker of [true, false]) {
    for (const defense of [true, false]) GRADED_SHAPES.push(shapeCode(base, kicker, defense));
  }
}

function shapeSlots(base, kicker, defense) {
  if (!(base in SHAPE_BASES)) throw new Error("unknown lineup base " + base);
  return SHAPE_BASES[base].concat(kicker ? ["K"] : [], defense ? ["DEF"] : []);
}

// The shape a code names (a seat link's t=, an old radio value), or null.
function shapeFromCode(code) {
  code = code === "std-nokd" ? "nokd" : code;
  for (const base of Object.keys(SHAPE_BASES)) {
    for (const kicker of [true, false]) {
      for (const defense of [true, false]) {
        if (shapeCode(base, kicker, defense) === code) {
          return { base, kicker, defense, code, graded: GRADED_SHAPES.includes(code) };
        }
      }
    }
  }
  return null;
}

// The shape these exact slots are, or null.
function shapeOfSlots(slots) {
  const want = (slots || []).join(",");
  for (const base of Object.keys(SHAPE_BASES)) {
    for (const kicker of [true, false]) {
      for (const defense of [true, false]) {
        if (shapeSlots(base, kicker, defense).join(",") === want) {
          return shapeFromCode(shapeCode(base, kicker, defense));
        }
      }
    }
  }
  return null;
}

// Exposed under ONE name in both worlds. In node the tests require() it; in a
// browser there is no module system here, so the page needs a global — and the
// page must not re-declare any of these names, because a plain <script> shares
// the global scope and a second `const REF_RE` is a SyntaxError that kills the
// whole file silently from the page's point of view.
const R = { normalize, stripDecoration, buildDirectory, resolveLine, resolveAll,
            suggestPlayers, enterPick, addPick, encodeRoster, packOne, REF_RE,
            MAX_ROSTER, SIZE_CODE, withVia, splitVia, decodeRoster, shapeCode,
            shapeSlots, shapeFromCode, shapeOfSlots, SHAPE_BASES, GRADED_SHAPES,
            exactName, unglue };
if (typeof module !== "undefined" && module.exports) {
  module.exports = R;
} else {
  globalThis.R = R;
}
