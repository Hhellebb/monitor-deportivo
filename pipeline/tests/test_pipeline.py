"""Pruebas unitarias para utilidades, traductor, curador multi-mercado, parlays y grading."""

from __future__ import annotations

from datetime import UTC, date, datetime
import json
from pathlib import Path

import pytest

from pipeline.curate import (
    CuratedMatch,
    CuratedPrediction,
    curate_community_top_records,
    curate_football_multi_market_picks,
    curate_match_vote_record,
    curate_tipster_profile,
    merge_and_select_daily_picks,
    resolve_allowed_league,
    select_reference_odds,
)
from pipeline.grade import MatchOutcome, calculate_tipster_stats, grade_prediction
from pipeline.parlay import ParlayLegCandidate, build_daily_parlay, grade_parlay
from pipeline.translator import normalize_and_translate
from pipeline.utils import (
    extract_event_id,
    extract_team_ids_from_url,
    normalize_match_url,
    parse_kickoff_utc,
    to_utc_iso,
)

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"


# ---------------------------------------------------------------------------
# 1. URLs, IDs, team_ids y fechas UTC
# ---------------------------------------------------------------------------
def test_event_id_team_ids_and_url_normalization():
    url_mirror = "https://www.cuotasahora.com/football/h2h/cruz-azul-G8PFBMll/guadalajara-Y5TaMKY6/#ABOBNplI"
    url_community = "https://www.oddsportal.com/football/h2h/cruz-azul-G8PFBMll/guadalajara-Y5TaMKY6/#ABOBNplI:1X2;2"

    assert extract_event_id(url_mirror) == "ABOBNplI"
    assert extract_event_id(url_community) == "ABOBNplI"
    assert extract_team_ids_from_url(url_mirror) == ["G8PFBMll", "Y5TaMKY6"]
    assert normalize_match_url(url_mirror) == normalize_match_url(url_community)


def test_parse_kickoff_utc_variants():
    dt1 = parse_kickoff_utc(match_date="2026-11-23 20:00:00 UTC")
    assert dt1 is not None and to_utc_iso(dt1) == "2026-11-23T20:00:00Z"

    dt2 = parse_kickoff_utc(
        kickoff=None,
        kickoff_text="Mañana 20:00 Mañana, 20:00 1X2",
        scraped_at="2026-11-22T22:08:02+00:00",
    )
    assert dt2 is not None and to_utc_iso(dt2) == "2026-11-23T20:00:00Z"

    dt3 = parse_kickoff_utc(
        kickoff=None,
        kickoff_text="Hoy 23:00 Hoy, 23:00 H/A, prór.",
        scraped_at="2026-11-22T22:08:42+00:00",
    )
    assert dt3 is not None and to_utc_iso(dt3) == "2026-11-22T23:00:00Z"


# ---------------------------------------------------------------------------
# 2. Traductor a español natural
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("market", "outcome", "sport", "expected_market", "expected_pick", "expected_es"),
    [
        ("1X2", "1", "football", "1X2", "Home", "Gana Club América"),
        ("1X2", "X", "football", "1X2", "Draw", "Empate"),
        ("1X2", "2", "football", "1X2", "Away", "Gana Chivas"),
        ("Over/Under 2.5", "Over 2.5", "football", "Over/Under 2.5", "Over 2.5", "Más de 2.5 goles"),
        ("Over/Under 2.5", "Under 2.5", "football", "Over/Under 2.5", "Under 2.5", "Menos de 2.5 goles"),
        ("Over/Under 218.5", "Over", "basketball", "Over/Under 218.5", "Over 218.5", "Más de 218.5 puntos"),
        ("Over/Under 46.5", "Under", "american-football", "Over/Under 46.5", "Under 46.5", "Menos de 46.5 puntos"),
        ("BTTS", "Yes", "football", "BTTS", "Yes", "Ambos equipos anotan"),
        ("Double Chance", "1X", "football", "Double Chance", "1X", "Club América gana o empata"),
        ("H/A, prór.", "1", "basketball", "Moneyline", "Home", "Gana Club América (Incluye T. Extra)"),
        ("Draw No Bet", "2", "football", "Draw No Bet", "Away", "Gana Chivas (Empate anula)"),
    ],
)
def test_normalize_and_translate(market, outcome, sport, expected_market, expected_pick, expected_es):
    res = normalize_and_translate(market, outcome, "Club América", "Chivas", sport=sport)
    assert res is not None
    assert res.market_raw == expected_market
    assert res.pick_raw == expected_pick
    assert res.pick_label_es == expected_es


# ---------------------------------------------------------------------------
# 3. Alcance de 5 ligas, bet365, multi-mercado y deduplicación
# ---------------------------------------------------------------------------
def test_league_scope_five_target_leagues():
    assert resolve_allowed_league("Liga MX", "football", "México") == ("football", "Liga MX")
    assert resolve_allowed_league("LaLiga", "football", "España") == ("football", "LaLiga")
    assert resolve_allowed_league("Bundesliga", "football", "Alemania") == ("football", "Bundesliga")
    assert resolve_allowed_league("Bundesliga", "football", "Austria") is None
    assert resolve_allowed_league("NBA", "basketball", "Estados Unidos") == ("basketball", "NBA")
    assert resolve_allowed_league("NFL", "american-football", "USA") == ("american-football", "NFL")
    assert resolve_allowed_league("Süper Lig", "football", "Turquía") is None


def test_select_reference_odds_prefers_bet365_with_fallback():
    rows_with_b365 = [
        {"1": "1.90", "bookmaker_name": "1xBet"},
        {"1": "1.83", "bookmaker_name": "bet365"},
        {"1": "1.88", "bookmaker_name": "Codere"},
    ]
    val, bookie = select_reference_odds(rows_with_b365, "1")
    assert val == 1.83 and bookie == "bet365"

    rows_no_b365 = [
        {"1": "1.90", "bookmaker_name": "1xBet", "blocked_outcomes": ["1"]},
        {"1": "1.85", "bookmaker_name": "Codere"},
        {"1": "1.82", "bookmaker_name": "Betway"},
    ]
    val2, bookie2 = select_reference_odds(rows_no_b365, "1")
    assert val2 == 1.85 and bookie2 == "Codere"


def test_curate_football_multi_market_picks():
    mrec = {
        "match_link": "https://www.oddsportal.com/football/h2h/a-11111111/b-22222222/#MULTI001",
        "match_date": "2026-11-23 20:00:00 UTC",
        "home_team": "Bayern Munich",
        "away_team": "Dortmund",
        "double_chance_market": [{"1X": "1.36", "bookmaker_name": "bet365"}],
        "btts_market": [{"btts_yes": "1.62", "btts_no": "2.25", "bookmaker_name": "bet365"}],
        "over_under_2_5_market": [{"over_odds": "1.55", "under_odds": "2.45", "bookmaker_name": "bet365"}],
    }
    picks = curate_football_multi_market_picks(
        mrec,
        league_name="Bundesliga",
        home_team_stats={"form": "W,W,W,D,W", "btts_pct": 80.0, "over_2_5_pct": 83.0},
        away_team_stats={"form": "W,L,W,W,D", "btts_pct": 75.0, "over_2_5_pct": 75.0},
        vote_breakdown_1x2=[{"outcome": "1", "pct": 72}, {"outcome": "X", "pct": 14}, {"outcome": "2", "pct": 14}],
    )
    markets_found = {p.market_raw for p in picks}
    assert {"Double Chance", "BTTS", "Over/Under 2.5"} <= markets_found
    assert all(p.bookmaker == "bet365" for p in picks)
    assert all(p.match.home_form == "W,W,W,D,W" for p in picks)


def test_curate_real_phase1_basketball_sample():
    sample_path = SAMPLES_DIR / "community_basketball.json"
    if not sample_path.exists():
        pytest.skip("Sample de Fase 1 no disponible en este entorno")

    records = json.loads(sample_path.read_text(encoding="utf-8"))
    picks = curate_community_top_records(records)
    assert len(picks) >= 1
    assert all(p.match.league == "NBA" for p in picks)
    assert all((p.consensus_pct or 0) >= 70 for p in picks)


def test_merge_duplicates_and_match_vote_record():
    match = CuratedMatch(
        id="EV001",
        external_url="https://www.oddsportal.com/football/h2h/a/b/#EV001",
        sport="football",
        league="Liga MX",
        home_team="Club América",
        away_team="Chivas",
        start_time="2026-11-23T02:00:00Z",
    )
    p_comm = CuratedPrediction(
        match=match,
        source_type="community",
        source_name="Consenso Comunidad",
        market_raw="1X2",
        pick_raw="Home",
        pick_label_es="Gana Club América",
        odds=1.85,
        consensus_pct=82,
        vote_breakdown=[{"outcome": "1", "pct": 82}],
        confidence_rank=8,
        bookmaker="Codere",
        supporting_sources=["Consenso Comunidad"],
    )
    p_tip = CuratedPrediction(
        match=match,
        source_type="tipster",
        source_name="BLAPRO",
        market_raw="1X2",
        pick_raw="Home",
        pick_label_es="Gana Club América",
        odds=1.82,
        consensus_pct=82,
        vote_breakdown=None,
        confidence_rank=8,
        bookmaker="bet365",
        supporting_sources=["BLAPRO"],
    )

    merged = merge_and_select_daily_picks([p_comm, p_tip])
    assert len(merged) == 1
    assert merged[0].source_type == "hybrid"
    assert merged[0].confidence_rank == 9
    assert merged[0].bookmaker == "bet365"
    assert merged[0].odds == 1.82

    vote_rec = {
        "mode": "match",
        "match_url": "https://www.cuotasahora.com/football/h2h/a/b/#CSnuq6U8",
        "event_id": "CSnuq6U8",
        "home_team": "Bayern",
        "away_team": "Mainz",
        "kickoff": "Monday, 23 Nov 2026, 20:00",
        "is_prematch": True,
        "markets": [{"market": "1X2", "outcomes": [{"outcome": "1", "votes_pct": 85}]}],
    }
    pick = curate_match_vote_record(
        vote_rec,
        league_name="Bundesliga",
        sport="football",
        odds_by_outcome={"1": (1.42, "bet365")},
    )
    assert pick is not None and pick.bookmaker == "bet365"


def test_curate_tipster_profile_skips_finished_and_low_winrate():
    profile = {
        "username": "PRO_TIPSTER",
        "privacy": "public",
        "scraped_at": "2026-11-22T12:00:00+00:00",
        "predictions": [
            {
                "kickoff": "2026-11-23T20:00",
                "market": "1X2",
                "home_team": "Real Madrid",
                "away_team": "Sevilla",
                "score": None,
                "pick_odds": 1.55,
                "outcomes": [
                    {"odds": 1.55, "community_pct": 82, "picked": True},
                    {"odds": 4.00, "community_pct": 10, "picked": False},
                    {"odds": 5.50, "community_pct": 8, "picked": False},
                ],
                "match_url": "https://www.oddsportal.com/football/h2h/a/b/#FUTURE01:1X2;2",
            }
        ],
    }
    now = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    assert curate_tipster_profile(profile, tipster_win_rate=52.0, now_utc=now) == []
    picks = curate_tipster_profile(profile, tipster_win_rate=64.0, now_utc=now)
    assert len(picks) == 1 and picks[0].pick_label_es == "Gana Real Madrid"


# ---------------------------------------------------------------------------
# 4. Combinada (Parlay) diaria: generación y calificación con ajuste void
# ---------------------------------------------------------------------------
def test_build_daily_parlay_distinct_matches_and_conservative_odds():
    cands = [
        ParlayLegCandidate(1, "M1", 1.45, 9, 88, "Gana Miami Heat"),
        ParlayLegCandidate(2, "M1", 1.50, 8, 82, "Más de 218.5 puntos"),  # mismo partido M1 -> debe omitirse
        ParlayLegCandidate(3, "M2", 1.60, 9, 84, "Bayern gana o empata"),
        ParlayLegCandidate(4, "M3", 1.38, 8, 80, "Gana Chiefs"),
        ParlayLegCandidate(5, "M4", 2.25, 10, 90, "Gana Underdog"),  # fuera de [1.30, 1.70]
    ]
    plan = build_daily_parlay(cands, parlay_date=date(2026, 11, 22))
    assert plan is not None
    assert len(plan.legs) == 3
    assert {l.match_id for l in plan.legs} == {"M1", "M2", "M3"}
    assert plan.total_odds == round(1.45 * 1.60 * 1.38, 2)


def test_grade_parlay_all_scenarios():
    # Todos ganados
    assert grade_parlay([("won", 1.50), ("won", 1.40)]) == ("won", 2.10)
    # Falla al menos 1 (incluso si otro sigue pending) -> lost inmediato
    assert grade_parlay([("lost", 1.50), ("pending", 1.40)]) == ("lost", 2.10)
    # 1 ganado + 1 pendiente -> sigue pending
    assert grade_parlay([("won", 1.50), ("pending", 1.40)]) == ("pending", None)
    # 2 ganados + 1 void -> won con momio ajustado solo por los ganados
    assert grade_parlay([("won", 1.50), ("won", 1.40), ("void", 1.60)]) == ("won", 2.10)
    # Todos void -> void @ 1.00
    assert grade_parlay([("void", 1.50), ("void", 1.40)]) == ("void", 1.00)


# ---------------------------------------------------------------------------
# 5. Motor de calificación individual (Grading) y casos borde críticos
# ---------------------------------------------------------------------------
def test_grade_football_standard_and_extra_time():
    m = MatchOutcome(sport="football", status="finished", home_score=2, away_score=1, partial_results="(1:0, 1:1)")
    assert grade_prediction("1X2", "Home", m) == "won"
    assert grade_prediction("Over/Under 2.5", "Over 2.5", m) == "won"
    assert grade_prediction("BTTS", "Yes", m) == "won"
    assert grade_prediction("Double Chance", "1X", m) == "won"

    # Empate 1-1 en 90' definido en penales (OddsPortal 2-1 con 4 parciales)
    m_pen = MatchOutcome(
        sport="football",
        status="finished",
        home_score=2,
        away_score=1,
        partial_results="(0:1, 1:0, 0:0, 4:3)",
    )
    assert grade_prediction("1X2", "Home", m_pen) == "lost"
    assert grade_prediction("1X2", "Draw", m_pen) == "won"
    assert grade_prediction("Draw No Bet", "Home", m_pen) == "void"


def test_grade_nba_nfl_overtime_and_voids():
    m_nba = MatchOutcome(sport="basketball", status="finished", home_score=118, away_score=114)
    assert grade_prediction("Moneyline", "Home", m_nba) == "won"
    assert grade_prediction("Over/Under 225.5", "Over 225.5", m_nba) == "won"

    m_nfl = MatchOutcome(sport="american-football", status="finished", home_score=27, away_score=24)
    assert grade_prediction("Moneyline", "Home", m_nfl) == "won"
    assert grade_prediction("Over/Under 46.5", "Over 46.5", m_nfl) == "won"

    m_post = MatchOutcome(sport="football", status="postponed", home_score=None, away_score=None)
    assert grade_prediction("1X2", "Home", m_post) == "void"


def test_calculate_tipster_stats_excludes_void_and_pending():
    assert calculate_tipster_stats(["won", "won", "lost", "void", "pending"]) == (3, 2, 66.67)
