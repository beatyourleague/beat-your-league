"""The league-app help pages — site/espn/, site/yahoo/, site/sleeper/, site/cbs/.

Usage:
    python -m render.platforms            # write the four pages
    python -m render.platforms --check    # fail if any page is stale (the suite does)

"espn start sit tool", "yahoo sit start suggestions" and "sleeper start sit"
are what managers type, and "I copied it from Yahoo — will it work?" is the
commonest question a reply can answer with a link (G5, Oct 2026). Each page
says how to bring that app's roster over and what the report does with it.

**Substance per page, or no page.** Four pages that differ only by a name are
doorway pages under Google's spam policy, so each carries what is TRUE OF
THAT APP: the copy format the paste reader actually handles (every line on a
page is backed by a tests/test_intake.py PASTES fixture of that app, which the
suite runs in Python and in the browser), a real slice of that copy shown as
the roster box reads it (resolved by the same directory in the suite), and the
app's default lineup in our terms — only the claims the join page already
makes. If that substance cannot be kept, ship one hub page instead.

Claims are bounded the same way as every selling surface: no price (so no
disclosure is needed), no accuracy comparison, no grades, no betting words,
"report" never "file", and "Not affiliated with <app>" in every footer.

GENERATED — never edit the pages by hand. The ask follows the landing's
CHECKOUT_OPEN (render.report.sample_cta) when the pages are written, so
flipping checkout means re-running this, and ``--check`` fails until then.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from render.report import (FAVICON_LINK, PAGE_META, SITE_BAR_CSS, SITE_ORIGIN,
                           SOCIAL_IMAGE_TAGS, esc, font_preloads, sample_cta, site_bar,
                           with_counter)

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
# Contract C7: the free planner lives at /byes/; one folder down it is "../byes/".
PLANNER_HREF = "../byes/"


@dataclass(frozen=True)
class Platform:
    slug: str                 # the folder under site/
    name: str                 # how the app names itself
    lineup: str               # its default lineup, in the join page's terms
    paste: str                # what its copy looks like, and how it is read
    pastes: tuple[str, ...]   # the tests/test_intake.py PASTES fixtures behind ``paste``
    example: tuple[str, ...]  # a contiguous slice of pastes[0]'s copy, shown raw
    reads: tuple[str, ...]    # what that slice resolves to (checked in the suite)
    shape: str                # the join page's lineup choice for this app ("" = theirs)


# One table, so the four pages cannot drift into four templates.
PLATFORMS = (
    Platform(
        slug="espn", name="ESPN",
        lineup="ESPN's default lineup is the one we call Standard: QB, 2 RB, 2 WR, TE, "
               "FLEX, K and D/ST.",
        paste="A copy of ESPN's roster table works as it comes — positions, teams, "
              "opponents, projections and tags like Q, OUT or IR included.",
        pastes=("espn", "espn-table", "espn-desktop", "espn-lines"),
        example=("Josh Allen  QB BUF  OUT", "Saquon Barkley  RB PHI  DTD",
                 "Ja'Marr Chase  WR CIN  P: 15.2 22.1", "Sam LaPorta  TE DET  Q",
                 "Ravens D/ST  D/ST", "Jake Bates  K DET  IR"),
        reads=("Josh Allen", "Saquon Barkley", "Ja'Marr Chase", "Sam LaPorta",
               "Baltimore Ravens", "Jake Bates"),
        shape="Standard"),
    Platform(
        slug="yahoo", name="Yahoo",
        lineup="Yahoo's default lineup is the one we call Standard.",
        paste="Yahoo's copy puts each player's team and position on the line under his "
              "name (“Buf - QB”). We read that as part of his line, never as an extra "
              "defense.",
        pastes=("yahoo",),
        example=("K", "Jake Bates", "Det - K", "DEF", "Denver Broncos", "Den - DEF", "BN",
                 "Courtland Sutton", "Den - WR"),
        reads=("Jake Bates", "Denver Broncos", "Courtland Sutton"),
        shape="Standard"),
    Platform(
        slug="sleeper", name="Sleeper",
        lineup="Sleeper's default lineup is the one we call Two FLEX: QB, 2 RB, 2 WR, TE, "
               "2 FLEX, K and DEF.",
        paste="Sleeper's copy puts position and team under each name (“QB - BUF”) and "
              "sometimes shortens first names (“J. Mixon”). Both are read, and a short "
              "name that fits two players is shown to you to pick.",
        pastes=("sleeper",),
        example=("Broncos", "DEF - DEN", "Chase Brown", "RB - CIN", "J. Mixon", "RB - HOU",
                 "D. Adams", "WR"),
        reads=("Denver Broncos", "Chase Brown", "Joe Mixon", "Davante Adams"),
        shape="Two FLEX"),
    Platform(
        slug="cbs", name="CBS",
        lineup="Pick the lineup your league starts: Standard, Two FLEX, Three WR or "
               "Superflex, with or without a K and a DEF.",
        paste="CBS lists names last-first (“St. Brown, Amon-Ra”) and writes defenses like "
              "“Broncos D/ST”. Both are read.",
        pastes=("cbs",),
        example=("Josh Allen, QB BUF", "Barkley, Saquon RB PHI", "St. Brown, Amon-Ra WR DET",
                 "Kittle, George TE SF", "Broncos D/ST", "Jake Bates, K DET"),
        reads=("Josh Allen", "Saquon Barkley", "Amon-Ra St. Brown", "George Kittle",
               "Denver Broncos", "Jake Bates"),
        shape=""),
)

TITLE = "{name} fantasy football start/sit report for your roster — Beat Your League"
DESCRIPTION = ("Copy your {name} fantasy roster and paste it, no login: every Tuesday a "
               "report decides your lineup — every slot decided, close calls explained, byes "
               "checked through Week 17.")
H1 = "Your {name} roster, decided every Tuesday"
STEPS = (
    "On a computer, open your team's roster page on {name}. On a phone, skip to step 3.",
    "Select from your first starter down to your last bench player, copy it, and paste it "
    "into the roster box. Extra text rides along fine.",
    "Or type each name into “Add a player” and tap him — any part of his name finds him.",
    "Pick your scoring, league size and starting lineup. {lineup}",
)
DOES_LEAD = "Every Tuesday through your title game:"
DOES = ("every slot decided for that roster",
        "each close call naming the bench player and the points gap",
        "an if/then for questionable starters",
        "a Saturday note only if Friday's injury report changes your lineup",
        "every bye ahead checked through the playoffs")
DOESNT = ("It doesn't connect to {name} or set your lineup there — you make the moves. "
          "Roster changed? Update it from the link in any report, or reply with it.")
PLANNER_LINK = "Free: check your roster's byes through Week 17"
# The join page's own words for what is scored (site/join/index.html).
SETTINGS_LINE = ("Full PPR, half PPR or standard scoring, in a league of 8, 10, 12 or 14 "
                 "teams.")
# The join page's lineup choices, in the order it offers them.
# The join page's own codes for them (site/join/roster.js shapeCode, with a K
# and a DEF), so a link from an app's page opens join/ on that app's default
# lineup (?t=, read by join's settingsFromLink) — T5: Sleeper said Two FLEX
# and its links opened join/ on Standard.
SHAPE_CODES = {"Standard": "std", "Two FLEX": "flex2", "Three WR": "wr3", "Superflex": "sf"}
SHAPES = (("Standard", "QB · 2 RB · 2 WR · TE · FLEX · K · DEF"),
          ("Two FLEX", "QB · 2 RB · 2 WR · TE · 2 FLEX · K · DEF"),
          ("Three WR", "QB · 2 RB · 3 WR · TE · FLEX · K · DEF"),
          ("Superflex", "Standard plus a second flex that can take a QB"))

STYLE = """
  :root{--display:'Barlow Condensed','Barlow Condensed Fallback','Arial Narrow',sans-serif;--sans:'Barlow','Barlow Fallback',-apple-system,'Segoe UI',Arial,sans-serif;--navy:#101E33;--paper:#F6F4EE;--card:#FFF;--turf:#1E7A46;--flag:#F2C230;
    --brick:#B3402F;--slate:#5A6B80;--ink2:#33445C;--line:#E2DDD0;--rule:#EEEAE1;--dusk:#BCC9DB;
    --elev-2:0 1px 2px rgba(16,30,51,.06),0 8px 24px -12px rgba(16,30,51,.18);}
  *{margin:0;padding:0;box-sizing:border-box;}
@@SITEBAR@@  /* Full-bleed paper (contract C2 of the truth pass): a flat navy band, then
     the page on the paper, edge to edge at every width — no sheet, no frame,
     no double rules. */
  body{background:var(--paper);font-family:var(--sans);color:var(--navy);padding:0;
    -webkit-font-smoothing:antialiased;}
  .wrap{max-width:760px;margin:0 auto;padding:0 24px;}
  header{background:var(--navy);color:var(--paper);}
  header .wrap{padding-top:32px;padding-bottom:48px;}
  .kicker{margin-top:40px;font-family:var(--display);font-weight:700;font-size:13px;
    letter-spacing:.08em;text-transform:uppercase;color:#B9C2D0;}
  header h1{font-family:var(--display);font-weight:800;font-size:clamp(34px,4.6vw,48px);line-height:1;
    text-transform:uppercase;margin-top:8px;text-wrap:balance;}
  header p{margin-top:14px;font-size:18px;color:var(--dusk);line-height:1.5;max-width:640px;}
  main{padding-bottom:72px;}
  /* Past the nav to the content, for a keyboard (the landing's own). */
  .skip{position:absolute;left:12px;top:-60px;z-index:100;background:var(--flag);color:var(--navy);
    font-weight:700;padding:10px 14px;border-radius:8px;text-decoration:none;}
  .skip:focus{top:12px;}
  main a,p a,li a{color:var(--navy);text-decoration:underline;text-underline-offset:3px;
    text-decoration-thickness:1px;text-decoration-color:color-mix(in srgb,currentColor 45%,transparent);}
  main a:hover,p a:hover,li a:hover{color:var(--brick);}
  main a:focus-visible{outline:3px solid var(--navy);outline-offset:2px;}
  /* Sections: a slate number, then the heading — no rule between them. */
  h2{font-family:var(--display);font-weight:800;font-size:clamp(28px,3.6vw,40px);line-height:1.05;
    text-transform:uppercase;color:var(--navy);margin:48px 0 12px;text-wrap:balance;}
  h2 .n{display:block;font-size:13px;font-weight:700;letter-spacing:.08em;color:var(--slate);
    margin-bottom:6px;}
  p,li{font-size:16px;line-height:1.6;color:var(--ink2);margin:10px 0;}
  b{color:var(--navy);}
  /* The steps: one paper card, a row each, a gold numeral in a navy circle. */
  ol.how{list-style:none;counter-reset:step;margin:16px 0 4px;background:var(--card);
    border:1px solid var(--line);border-radius:12px;box-shadow:var(--elev-2);overflow:hidden;}
  ol.how li{counter-increment:step;position:relative;margin:0;padding:16px 18px 16px 62px;
    border-top:1px solid var(--rule);}
  ol.how li:first-child{border-top:0;}
  ol.how li::before{content:counter(step);position:absolute;left:18px;top:14px;width:28px;height:28px;
    display:flex;align-items:center;justify-content:center;border-radius:50%;background:var(--navy);
    color:var(--flag);font-family:var(--display);font-weight:800;font-size:14px;line-height:1;}
  /* The lineup templates (contract C7's tag): 4px corners. */
  .shapes{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 4px;}
  .shape{font-size:13px;font-weight:600;color:var(--slate);border:1px solid var(--line);
    background:var(--card);border-radius:4px;padding:4px 10px;}
  .shape b{font-family:var(--display);font-size:12px;font-weight:800;letter-spacing:.06em;
    text-transform:uppercase;margin-right:6px;}
  .shape.is{border-color:var(--navy);color:var(--navy);background:#FBF3D9;}
  .paste{display:grid;grid-template-columns:minmax(0,1.15fr) 40px minmax(0,1fr);align-items:start;
    margin:16px 0 6px;}
  .pcol{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;
    box-shadow:var(--elev-2);}
  .phead{background:var(--navy);color:var(--paper);font-family:var(--display);font-weight:800;
    font-size:14px;letter-spacing:.08em;text-transform:uppercase;padding:10px 16px;}
  .praw{margin:0;padding:14px 16px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    font-size:13px;line-height:1.6;color:var(--ink2);white-space:pre-wrap;overflow-wrap:anywhere;}
  .pread{list-style:none;padding:8px 16px 10px;}
  .pread li{display:flex;align-items:center;gap:10px;margin:0;padding:8px 0;font-weight:700;
    color:var(--navy);border-top:1px solid var(--rule);font-size:15px;line-height:1.35;}
  .pread li:first-child{border-top:0;}
  .pread svg{width:16px;height:16px;flex:none;}
  .parrow{display:flex;align-items:center;justify-content:center;align-self:center;}
  .parrow svg{width:22px;height:22px;}
  .pnote{font-size:13px;color:var(--slate);margin:8px 0 0;}
  ul.does{list-style:none;margin:12px 0 4px;}
  ul.does li{position:relative;padding:3px 0 3px 30px;margin:4px 0;}
  /* The landing's own check: a turf circle, a white tick. */
  ul.does li::before{content:"";position:absolute;left:2px;top:.45em;width:18px;height:18px;
    border-radius:50%;background:var(--turf) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14'%3E%3Cpath d='M4 7.2l2 2 4-4.4' fill='none' stroke='%23fff' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center/100% no-repeat;}
  /* A notice: the report's tint for something to read first. */
  .note{margin:16px 0;padding:14px 16px;background:#FBF3D9;border:1px solid #EBDDAE;border-radius:12px;}
  /* Contract C7: the site's one button — a flat rounded rectangle. */
  .btn{display:inline-flex;align-items:center;justify-content:center;min-height:48px;padding:0 22px;
    border:0;border-radius:8px;font-family:var(--display);font-weight:800;font-size:16px;line-height:1;
    letter-spacing:.06em;text-transform:uppercase;text-decoration:none;cursor:pointer;text-align:center;
    transition:transform .18s cubic-bezier(.22,1,.36,1);}
  .btn.gold{color:var(--navy);background:var(--flag);}
  .btn.gold:hover{background:#FFD24A;}
  .btn.ghost{background:transparent;color:var(--navy);border:1.5px solid var(--navy);}
  .btn:hover{transform:translateY(-1px);}
  main a.btn,main a.btn:hover,header a.btn,header a.btn:hover{color:var(--navy);text-decoration:none;}
  header a:focus-visible{outline:3px solid var(--flag);outline-offset:2px;}
  @media (prefers-reduced-motion: reduce){.btn{transition:none;transform:none!important;}}
  .cta{display:flex;gap:12px 16px;flex-wrap:wrap;align-items:center;margin:24px 0 4px;}
  header .cta{margin-top:24px;}
  .free{font-size:15px;font-weight:700;}
  header .free a{color:#FFFFFF;text-decoration:underline;text-underline-offset:3px;
    text-decoration-color:rgba(255,255,255,.45);display:inline-block;padding:6px 0;}
  main .free a{display:inline-block;padding:6px 0;}
  .apps{margin:28px 0 0;font-size:15px;color:var(--slate);}
  .apps a{display:inline-block;padding:6px 2px;margin-right:6px;font-weight:700;}
  .apps a[aria-current]{color:var(--slate);text-decoration:none;}
  footer{border-top:1px solid var(--line);}
  footer .wrap{padding-top:24px;padding-bottom:40px;font-size:12px;color:var(--slate);line-height:1.6;}
  footer a{color:var(--navy);text-decoration:underline;text-underline-offset:3px;}
  @media (max-width:640px){
    .paste{grid-template-columns:1fr;}
    .parrow{height:34px;}
    .parrow svg{transform:rotate(90deg);}
  }
  @media (max-width:600px){
    .wrap{padding:0 16px;}
    header .wrap{padding-top:24px;padding-bottom:32px;}
    .kicker{margin-top:32px;}
    header p{font-size:16px;}
    .cta .btn{width:100%;min-height:52px;}
    ol.how li{padding-left:56px;padding-right:14px;}
    ol.how li::before{left:14px;}
  }
"""

_TICK = ('<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><circle cx="8" cy="8" '
         'r="8" fill="#1E7A46"/><path d="M4.4 8.3l2.4 2.4 4.8-5" fill="none" stroke="#F6F4EE" '
         'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
_ARROW = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M3 12h16m-6-6 6 6-6 6" '
          'fill="none" stroke="#5A6B80" stroke-width="2.4" stroke-linecap="round" '
          'stroke-linejoin="round"/></svg>')


def url_for(platform: Platform) -> str:
    return f"{SITE_ORIGIN}/{platform.slug}/"


def path_for(platform: Platform, site: Path = SITE) -> Path:
    return Path(site) / platform.slug / "index.html"


def join_href(platform: Platform) -> str:
    """join/, one folder down, on this app's default lineup when it has one."""
    code = SHAPE_CODES.get(platform.shape)
    return "../join/index.html" + (f"?t={code}" if code else "")


def _ask(platform: Platform) -> str:
    """The site's one ask, as the samples make it (render.report.sample_cta:
    closed, "Tell me when it opens" to the landing's capture; open, the join
    page, here on this app's default lineup), one folder down."""
    cta = sample_cta().replace('href="', 'href="../', 1)
    return cta.replace('href="../join/index.html"', f'href="{join_href(platform)}"', 1)


def _step(platform: Platform, i: int, step: str) -> str:
    """One how-to step, escaped; step 2's "the roster box" links to it (T4:
    the steps described a box the page never linked, so a reader following
    them had nowhere to paste — join/ checks a roster with checkout closed
    too, and keeps it with the waitlist email)."""
    text = esc(step.format(name=platform.name, lineup=platform.lineup))
    if i == 1:
        assert "the roster box" in text
        text = text.replace("the roster box",
                            f'<a href="{esc(join_href(platform))}">the roster box</a>', 1)
    return text


def _shapes(platform: Platform) -> str:
    chips = []
    for name, slots in SHAPES:
        here = ' class="shape is"' if name == platform.shape else ' class="shape"'
        chips.append(f'<span{here}><b>{esc(name)}</b>{esc(slots)}</span>')
    return f'<div class="shapes">{"".join(chips)}</div>'


def page(platform: Platform) -> str:
    from render.live_sample import with_via_carry
    name = platform.name
    title = TITLE.format(name=name)
    desc = DESCRIPTION.format(name=name)
    steps = "".join(f"<li>{_step(platform, i, step)}</li>" for i, step in enumerate(STEPS))
    raw = esc("\n".join(platform.example))
    reads = "".join(f"<li>{_TICK}{esc(n)}</li>" for n in platform.reads)
    does = "".join(f"<li>{esc(item)}</li>" for item in DOES)
    others = " ".join(
        (f'<a href="../{p.slug}/" aria-current="page">{esc(p.name)}</a>' if p == platform
         else f'<a href="../{p.slug}/">{esc(p.name)}</a>') for p in PLATFORMS)
    preloads = font_preloads().replace('href="fonts/', 'href="../fonts/')
    style = STYLE.replace("@@SITEBAR@@", SITE_BAR_CSS)
    body = f"""<!DOCTYPE html>
<!-- GENERATED by `python -m render.platforms` from render/platforms.py's PLATFORMS
     table. Do not edit by hand: `python -m render.platforms --check` (and the
     suite) fail when a page is stale. -->
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<link rel="canonical" href="{url_for(platform)}">
<meta name="description" content="{esc(desc)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Beat Your League">
{SOCIAL_IMAGE_TAGS}{FAVICON_LINK}
{PAGE_META}{preloads}<link rel="stylesheet" href="../fonts/fonts.css">
<style>{style}</style>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header>
  <div class="wrap">
    {site_bar("../")}
    <p class="kicker">For {esc(name)} leagues</p>
    <h1>{esc(H1.format(name=name))}</h1>
    <p>Paste the roster you already have on {esc(name)} — no login, nothing to connect.
    Every Tuesday a report built from it decides your lineup for your scoring.</p>
    <div class="cta">{_ask(platform)}<span class="free"><a href="{PLANNER_HREF}">{esc(PLANNER_LINK)}</a></span></div>
  </div>
</header>
<main id="main">
  <div class="wrap">
    <h2><span class="n">01</span>Bring your {esc(name)} roster over</h2>
    <ol class="how">{steps}</ol>
    {_shapes(platform)}
    <p>{esc(SETTINGS_LINE)}</p>
    <p><b>{esc(platform.paste)}</b></p>
    <div class="paste">
      <div class="pcol"><div class="phead">Copied from {esc(name)}</div><pre class="praw">{raw}</pre></div>
      <div class="parrow">{_ARROW}</div>
      <div class="pcol"><div class="phead">Read as</div><ul class="pread">{reads}</ul></div>
    </div>
    <p class="pnote">Part of a copy from {esc(name)}, shown the way the roster box reads it.</p>

    <h2><span class="n">02</span>What the report does with it</h2>
    <p>{esc(DOES_LEAD)}</p>
    <ul class="does">{does}</ul>

    <h2><span class="n">03</span>What it doesn't do</h2>
    <p class="note">{esc(DOESNT.format(name=name))}</p>

    <div class="cta">{_ask(platform)}<a class="btn ghost" href="../sample-report.html">See a real report</a></div>
    <p class="free"><a href="{PLANNER_HREF}">{esc(PLANNER_LINK)}</a></p>
    <p><a href="../how-it-works.html">How the report works</a>, section by section.</p>
    <p class="apps">Other league apps: {others}</p>
  </div>
</main>
<footer><div class="wrap"><b>Beat Your League</b> — analysis, not betting picks. Not affiliated with {esc(name)}.
  NFL data: nflverse (nflverse-data), CC-BY-4.0. Not affiliated with the NFL.<br>
  <a href="../terms.html">Terms &amp; refunds</a> · <a href="../privacy.html">Privacy</a></div></footer>
</body>
</html>
"""
    return with_counter(with_via_carry(body))


def build(site: Path = SITE) -> dict[Path, str]:
    return {path_for(p, site): page(p) for p in PLATFORMS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail when a page is not what this would write")
    args = parser.parse_args(argv)
    pages = build()
    if args.check:
        stale = [path for path, text in pages.items()
                 if not path.is_file() or path.read_text(encoding="utf-8") != text]
        for path in stale:
            print(f"STALE {path.relative_to(REPO_ROOT)} — run `python -m render.platforms`",
                  file=sys.stderr)
        if not stale:
            print(f"{len(pages)} league-app pages are current.")
        return 1 if stale else 0
    for path, text in pages.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
