"""The public prediction ledger page — site/ledger/index.html.

This is the proof asset PLAN.md's marketing leans on: every published call,
graded, in public, wins and misses alike. It renders in the report's paper
design (the product surface), not the landing page's dark shell — the dark
page sells, the paper record testifies.

Privacy: built exclusively from ``engine.ledger.public_entries`` — player
names and results only, no league ids, roster ids, or emails. Data is embedded
at build time; the page is static and needs no fetch.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from render.report import mark_svg
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "site" / "ledger"


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _row(entry: Mapping[str, Any]) -> str:
    outcome = entry.get("outcome") or entry.get("status")
    klass = {"hit": "hit", "miss": "miss", "tie": "tie", "void": "void"}.get(str(outcome), "")
    margin = entry.get("margin")
    if entry.get("status") == "void":
        result = esc(entry.get("void_reason") or "void")
    elif margin is not None:
        result = f"{'+' if margin >= 0 else ''}{margin:.1f}"
    else:
        result = "—"
    regret = ' <span class="tag">regret call</span>' if entry.get("regret") else ""
    return (
        f'<tr class="{klass}"><td>{esc(entry["season"])} · W{esc(entry["week"])}</td>'
        f'<td>{esc(entry["slot"])}</td>'
        f'<td><b>{esc(entry["pick"])}</b> over {esc(entry["over"])}{regret}</td>'
        f'<td class="num">{entry["confidence"]:.0%}</td>'
        f'<td class="stamp-{klass}">{esc(str(outcome).upper())}</td>'
        f'<td class="num">{result}</td></tr>'
    )


def render_ledger(entries: list[Mapping[str, Any]], summary: Mapping[str, Any],
                  generated_at: str | None = None) -> str:
    stamp = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    decided = summary.get("hits", 0) + summary.get("misses", 0)
    if entries:
        record_line = (f'{summary.get("hits", 0)}–{summary.get("misses", 0)}'
                       + (f'–{summary.get("ties", 0)}' if summary.get("ties") else ""))
        hit_rate = summary.get("hit_rate")
        rate_line = f"{hit_rate:.1%} on {decided} decided calls" if hit_rate is not None else ""
        buckets = "".join(
            f'<tr><td>{esc(b["label"])}</td><td class="num">{b["decided"]}</td>'
            f'<td class="num">{b["stated"]:.1%}</td><td class="num">{b["observed"]:.1%}</td></tr>'
            for b in summary.get("buckets", [])
        )
        bucket_table = (
            '<h2>Does the confidence number mean anything?</h2>'
            '<p class="note">Calibration, running: when we said X%, how often did the call hit? '
            'Small samples wobble — judge the gap, not single rows.</p>'
            '<div style="overflow-x:auto"><table><tr><th>Stated</th><th class="num">Decided</th>'
            '<th class="num">Stated avg</th><th class="num">Observed</th></tr>'
            f'{buckets}</table></div>'
        ) if summary.get("buckets") else ""
        body = (
            f'<div class="record"><b>{record_line}</b><span>{esc(rate_line)}</span></div>'
            f'{bucket_table}'
            '<h2>Every call, in the open</h2>'
            '<p class="note">Recorded the moment it was published, graded when the games went '
            'final, never edited after. Voids are shown, not hidden.</p>'
            '<div style="overflow-x:auto"><table><tr><th>Week</th><th>Slot</th><th>The call</th>'
            '<th class="num">Stated</th><th>Result</th><th class="num">Margin</th></tr>'
            + "".join(_row(e) for e in entries) + "</table></div>"
        )
    else:
        body = (
            '<div class="empty"><b>The rules are up before the first game.</b>'
            '<p>Here is what gets recorded, written down before anyone has played. Every call '
            'we send a subscriber is stamped before kickoff and graded against the real box '
            'score once the games are final, hit or miss, and nothing is edited afterwards. '
            'Calls need three games of record behind both players, so the first ones are made '
            'in week 4 and graded the Monday after — this page fills from October.</p>'
            '<span class="stampbox">RULES FROZEN &middot; NOTHING EDITED AFTER THE FACT</span></div>'
        )

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Beat Your League — The Receipts</title>
<meta name="description" content="Every published call, graded against real box scores after the games go final. Wins and misses both.">
<meta property="og:title" content="Beat Your League — The Receipts">
<meta property="og:description" content="Every published call, graded against real box scores after the games go final. Wins and misses both.">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Beat Your League">
<meta name="twitter:card" content="summary">
<!-- og:image needs the live absolute URL. After the domain exists, add:
     <meta property="og:image" content="https://YOUR-DOMAIN/og.png"> -->
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🧾</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;800&family=Barlow:wght@400;500;700;800&display=swap" rel="stylesheet">
<style>
  :root{{--navy:#101E33;--paper:#F6F4EE;--card:#FFFFFF;--turf:#1E7A46;--flag:#F2C230;
    --brick:#B3402F;--slate:#5A6B80;--ink2:#33445C;--line:#D8D3C6;}}
  *{{margin:0;padding:0;box-sizing:border-box;}}
  body{{background:#E7E4DA;font-family:'Barlow',sans-serif;color:var(--navy);padding:14px 8px 44px;}}
  .sheet{{max-width:860px;margin:0 auto;background:var(--paper);border:1px solid var(--line);
    box-shadow:0 2px 18px rgba(16,30,51,.10);}}
  header{{background:linear-gradient(180deg,#182A45,var(--navy));color:var(--paper);padding:26px 28px;}}
  header .brand{{display:inline-flex;align-items:center;gap:9px;font-family:'Barlow Condensed';font-weight:800;font-size:15px;letter-spacing:.24em;
    text-transform:uppercase;color:var(--flag);}}
  header .brand a{{color:inherit;text-decoration:none;}}
  header .brand svg.mark{{width:22px;height:15px;flex:none;}}
  header h1{{font-family:'Barlow Condensed';font-weight:800;font-size:42px;text-transform:uppercase;margin-top:6px;}}
  header p{{margin-top:8px;font-size:14px;color:#C9D4E2;line-height:1.55;max-width:560px;}}
  main{{padding:24px 28px 34px;}}
  h2{{font-family:'Barlow Condensed';font-weight:800;font-size:24px;text-transform:uppercase;margin:26px 0 6px;}}
  .note{{font-size:13px;color:var(--slate);line-height:1.5;margin-bottom:10px;}}
  .record{{display:flex;align-items:baseline;gap:14px;background:var(--card);
    border:2px solid var(--navy);padding:16px 18px;}}
  .record b{{font-family:'Barlow Condensed';font-weight:800;font-size:52px;line-height:1;}}
  .record span{{font-size:14px;color:var(--slate);font-weight:600;}}
  table{{width:100%;border-collapse:collapse;background:var(--card);border:2px solid var(--navy);
    font-size:14px;font-variant-numeric:tabular-nums;}}
  th{{background:var(--navy);color:#C9D4E2;font-family:'Barlow Condensed';font-weight:800;
    font-size:12px;letter-spacing:.12em;text-transform:uppercase;padding:8px 10px;text-align:left;}}
  td{{padding:9px 10px;border-top:1px solid #EDEAE1;}}
  th.num,td.num{{text-align:right;}}
  .tag{{font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;
    color:#8A6A10;background:#FBF3D9;padding:2px 6px;}}
  .stamp-hit{{color:var(--turf);font-weight:800;}}
  .stamp-miss{{color:var(--brick);font-weight:800;}}
  .stamp-tie,.stamp-void{{color:var(--slate);font-weight:800;}}
  .empty{{background:var(--card);border:2px solid var(--navy);padding:26px;line-height:1.6;}}
  .empty b{{font-family:'Barlow Condensed';font-weight:800;font-size:28px;text-transform:uppercase;}}
  .empty p{{margin-top:10px;font-size:14.5px;color:var(--ink2);max-width:560px;}}
  .stampbox{{display:inline-block;margin-top:16px;border:2px solid var(--turf);color:var(--turf);
    font-family:'Barlow Condensed';font-weight:800;letter-spacing:.16em;font-size:13px;
    text-transform:uppercase;padding:5px 12px;transform:rotate(-2deg);}}
  footer{{padding:18px 28px 26px;font-size:12px;color:var(--slate);line-height:1.6;
    border-top:3px double var(--line);}}
</style>
</head>
<body>
<div class="sheet">
  <header>
    <div class="brand">{mark_svg("byll")}<a href="../index.html">Beat Your League</a></div>
    <h1>The Receipts</h1>
    <p>Every call we send is stamped before kickoff and graded against the real box score once
    the games end. The rules that decide it were locked before the season, and nothing is edited
    after the fact.</p>
  </header>
  <main>{body}</main>
  <div style="padding:24px 28px;border-top:3px double var(--line);text-align:center;">
    <p style="margin:0 0 12px;font-size:15px;">Every row is a call we actually sent,
    recorded before kickoff and graded in the open. Your league's version starts when
    you pick a rival.</p>
    <a href="../join/index.html" style="display:inline-block;background:var(--turf);color:#fff;
      text-decoration:none;font-family:'Barlow Condensed';font-weight:800;font-size:17px;
      letter-spacing:.1em;text-transform:uppercase;padding:13px 26px;">Pick your rival</a>
  </div>
  <footer><b style="color:var(--navy)">Beat Your League</b> — analysis, not picks. No betting
  content, no staking advice. Page generated {esc(stamp)} · league identities of subscribers
  are never shown here.</footer>
</div>
</body>
</html>
'''


def write_ledger_site(entries: list[Mapping[str, Any]], summary: Mapping[str, Any],
                      out_dir: Path | None = None) -> Path:
    out_dir = out_dir if out_dir is not None else DEFAULT_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    page = out_dir / "index.html"
    page.write_text(render_ledger(entries, summary), encoding="utf-8")
    (out_dir / "data.json").write_text(
        json.dumps(entries, indent=1), encoding="utf-8")
    return page
