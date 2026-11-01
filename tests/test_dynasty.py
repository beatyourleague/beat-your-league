"""The dynasty page (owner decision, Oct 31 2026): what the weekly report does
for a dynasty or keeper manager today, and what it does not do."""

from __future__ import annotations

import html
import re
from pathlib import Path

from render import platforms
from run.refs import MAX_ROSTER

SITE = Path(__file__).resolve().parent.parent / "site"
PAGE = (SITE / "dynasty" / "index.html").read_text(encoding="utf-8")
WORDS = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", re.sub(
    r"<script.*?</script>|<style.*?</style>|<head>.*?</head>", " ", PAGE, flags=re.S))).split())


def test_the_page_is_generated_and_current() -> None:
    assert platforms.build(SITE)[SITE / "dynasty" / "index.html"] == PAGE


def test_dynasty_is_a_kind_of_league_not_an_app() -> None:
    assert platforms.DYNASTY not in platforms.PLATFORMS
    assert "Copied from" not in WORDS, "dynasty has no copy format of its own"


def test_the_roster_limit_is_the_one_the_page_enforces() -> None:
    assert f"up to {MAX_ROSTER} players" in WORDS
    assert f"More than {MAX_ROSTER} players? Leave out your IR and taxi players." in WORDS


def test_it_says_what_it_is_not() -> None:
    """Each line stops a buyer paying for something that does not exist."""
    for limit in ("It doesn't value trades, rank rookies or help with your startup or rookie draft",
                  "it isn't tuned for dynasty",
                  "Weekly reports run during the NFL season, not the off-season",
                  "TE premium and six-point passing touchdowns aren't scored yet",
                  "Their odds wait until they have enough games on record"):
        assert limit in WORDS, limit


def test_it_carries_no_price_and_promises_no_off_season_product() -> None:
    assert "$" not in WORDS
    assert not re.search(r"year[- ]round|coming soon|all year", WORDS, re.I)


def test_it_opens_join_with_no_lineup_chosen_for_the_manager() -> None:
    assert 'href="../join/index.html?t=' not in PAGE
    assert 'class="shape is"' not in PAGE


def test_every_app_page_and_the_landing_lead_to_it() -> None:
    for slug in ("espn", "yahoo", "sleeper", "cbs"):
        page = (SITE / slug / "index.html").read_text(encoding="utf-8")
        assert '<a href="../dynasty/">Dynasty or keeper league? See what you get</a>' in page
    landing = (SITE / "index.html").read_text(encoding="utf-8")
    assert '<a href="dynasty/">Dynasty and keeper leagues</a> too.' in landing
    assert "https://beatyourleague.com/dynasty/" in (SITE / "sitemap.xml").read_text(encoding="utf-8")


def test_the_page_is_counted_and_keeps_its_channel_tag() -> None:
    assert '"dynasty"' in (SITE / "count.js").read_text(encoding="utf-8")
    assert "(?:espn|yahoo|sleeper|cbs|dynasty)" in PAGE


# --------------------------------------------------------------------- #
# the league-type setting (owner decision, Oct 31 2026): included in the plan,
# one tap on the roster check, and it moves no number
# --------------------------------------------------------------------- #

import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402

from run.refs import REDRAFT, RefError, decode_roster, encode_roster, with_via  # noqa: E402

JOIN = (SITE / "join" / "index.html").read_text(encoding="utf-8")
ROSTER_JS = SITE / "join" / "roster.js"
SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
IDS = [f"00-{i:07d}" for i in range(1000, 1009)]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def test_a_redraft_ref_is_exactly_what_it_always_was() -> None:
    """No letter means every roster written before this reads the same."""
    plain = encode_roster("monthly", "ppr", SLOTS, IDS)
    assert plain == encode_roster("monthly", "ppr", SLOTS, IDS, league_type=REDRAFT)
    assert plain.split("-")[1] == "pcQRRWWTFKD09"
    assert decode_roster(plain).league_type == REDRAFT


@pytest.mark.parametrize("kind,letter", [("keeper", "k"), ("dynasty", "d")])
def test_the_league_type_rides_the_ref_and_a_channel_tag_still_fits(kind, letter) -> None:
    ref = encode_roster("monthly", "ppr", SLOTS, IDS, league_type=kind)
    assert ref.split("-")[1].endswith(f"09{letter}")
    assert decode_roster(ref).league_type == kind
    tagged = decode_roster(with_via(ref, "reddit"))
    assert (tagged.league_type, tagged.via, tagged.player_ids) == (kind, "reddit", tuple(IDS))


def test_an_unknown_league_type_is_refused() -> None:
    with pytest.raises(RefError):
        encode_roster("monthly", "ppr", SLOTS, IDS, league_type="bestball")


def test_the_longest_lineup_at_the_new_limit_fits_stripes_200() -> None:
    ids = [f"00-{i:07d}" for i in range(1000, 1000 + MAX_ROSTER)]
    slots = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "SUPER_FLEX", "K", "DEF"]
    ref = encode_roster("league_pass", "half_ppr", slots, ids, 14, league_type="dynasty")
    assert len(ref) <= 200 and decode_roster(ref).player_ids == tuple(ids)
    # A long channel tag gives way, never the roster.
    tagged = with_via(ref, "a" * 24)
    assert tagged == ref and decode_roster(tagged).league_type == "dynasty"


@needs_node
@pytest.mark.parametrize("kind", ["redraft", "keeper", "dynasty"])
def test_the_browser_and_python_write_the_same_ref(kind) -> None:
    script = (f"const R=require({str(ROSTER_JS)!r});"
              f"const ref=R.encodeRoster('monthly','ppr',{json.dumps(SLOTS)},{json.dumps(IDS)},12,"
              f"{json.dumps(kind)});"
              f"console.log(JSON.stringify([ref,R.decodeRoster(ref).leagueType,R.MAX_ROSTER]));")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    ref, league, limit = json.loads(out.stdout)
    assert ref == encode_roster("monthly", "ppr", SLOTS, IDS, league_type=kind)
    assert league == kind and limit == MAX_ROSTER


def test_the_setting_never_splits_the_public_record() -> None:
    """It moves no number, so a dynasty manager's calls land in the store
    every other manager with that scoring, size and lineup uses."""
    import inspect
    from engine.subscriber import ledger_store_id
    assert "league" not in " ".join(p for p in inspect.signature(ledger_store_id).parameters
                                    if p != "league_size")


def test_the_report_labels_the_league_and_nothing_else_changes() -> None:
    from render import anatomy
    base = {"meta": {"solo": True, "num_teams": 12, "scoring": "Full PPR", "week": 9},
            "lineup": []}
    assert anatomy.masthead(base)["meta"] == "12 teams · Full PPR"
    for kind, word in (("dynasty", "Dynasty"), ("keeper", "Keeper")):
        labelled = {**base, "meta": {**base["meta"], "league_type": kind}}
        assert anatomy.masthead(labelled)["meta"] == f"12 teams · Full PPR · {word}"


def test_a_change_of_league_type_is_a_real_update_and_links_carry_it() -> None:
    from run.updates import same_roster, settings_params
    plain = encode_roster("monthly", "ppr", SLOTS, IDS)
    dynasty = encode_roster("monthly", "ppr", SLOTS, IDS, league_type="dynasty")
    assert not same_roster(plain, dynasty)
    assert "league=dynasty" in settings_params(decode_roster(dynasty))
    assert not any(p.startswith("league=") for p in settings_params(decode_roster(plain)))


def test_the_buy_page_offers_it_in_one_tap_and_says_what_it_covers() -> None:
    radios = re.findall(r'<input type="radio" name="league" value="(\w+)"( checked)?>', JOIN)
    assert radios == [("redraft", " checked"), ("keeper", ""), ("dynasty", "")]
    settings = JOIN.split('<div id="step-league">')[1].split('<div id="settings-body" hidden>')[0]
    assert 'id="opt-league"' in settings, "it must be visible without pressing Change"
    assert "It doesn't cover trades or rookie drafts." in re.sub(
        r"\s+", " ", JOIN.split('id="league-note"')[1].split("</div>")[0])
    assert '["keeper", "dynasty"].includes(QUERY.get("league"))' in JOIN
    assert 'setRadio("league", RESTORED.leagueType' in JOIN
    assert 'radio("league"));' in JOIN.split("function checkoutRef()")[1].split("}")[0]


def test_the_dynasty_page_opens_the_buy_page_on_dynasty_and_offers_the_pass() -> None:
    assert PAGE.count('href="../join/index.html?league=dynasty"') >= 3
    assert "The League Pass gives every manager their own report." in WORDS
    assert "$" not in WORDS, "the page sells no separate price: dynasty is in the plan"


def test_demand_is_counted_in_all_three_places_alike() -> None:
    from run import stats
    worker = (SITE.parent / "infra" / "form-worker.js").read_text(encoding="utf-8")
    counter = (SITE / "count.js").read_text(encoding="utf-8")
    assert '"dynasty", "keeper"]' in worker and '"dynasty", "keeper"]' in counter
    assert {"dynasty", "keeper"} <= set(stats.COUNT_EVENTS)


def test_paid_signups_are_counted_by_league_type() -> None:
    from run.stats import _paid_by_league_line
    paid = {"status": "complete", "payment_status": "paid"}
    sessions = [{**paid, "client_reference_id": encode_roster("monthly", "ppr", SLOTS, IDS)},
                {**paid, "client_reference_id": encode_roster("monthly", "ppr", SLOTS, IDS,
                                                              league_type="dynasty")}]
    assert _paid_by_league_line(sessions).endswith("redraft 1, dynasty 1")
    assert _paid_by_league_line([]).endswith("none yet")
