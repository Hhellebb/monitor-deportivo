"""Pruebas unitarias para utilidades, traductor, curador y motor de grading."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from pipeline.curate import (
    CuratedMatch,
    CuratedPrediction,
    curate_community_top_records,
    curate_match_vote_record,
    curate_tipster_profile,
    merge_and_select_daily_picks,
    resolve_allowed_league,
)
from pipeline.grade import MatchOutcome, calculate_tipster_stats, grade_prediction
from pipeline.translator import normalize_and_translate
from pipeline.utils import extract_event_id, normalize_match_url, parse_kickoff_utc, to_utc_iso

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"


# ---------------------------------------------------------------------------
# 1. URLs, IDs y fechas UTC
# ---------------------------------------------------------------------------
def test_event_id_and_url_normalization():
    url_mirror = "https://www.cuotasahora.com/football/h2h/brentford-xYe7DwID/everton-KluSTr9s/#CSnuq6U8"
    url_community = "https://www.oddsportal.com/football/h2h/brentford-xYe7DwID/everton-KluSTr9s/#CSnuq6U8:1X2;2"

    assert extract_event_id(url_mirror) == "CSnuq6U8"
    assert extract_event_id(url_community) == "CSnuq6U8"
    assert normalize_match_url(url_mirror) == normalize_match_url(url_community)
    assert normalize_match_url(url_mirror) == (
        "https://www.oddsportal.com/football/h2h/brentford-xYe7DwID/everton-KluSTr9s/#CSnuq6U8"
    )


def test_parse_kickoff_utc_variants():
    # match_date estándar de upcoming/historic
    dt1 = parse_kickoff_utc(match_date="2026-11-23 20:00:00 UTC")
    assert dt1 is not None and to_utc_iso(dt1) == "2026-11-23T20:00:00Z"

    # Fallback en español del espejo cuotasahora.com ('Hoy' / 'Mañana')
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

    # Encabezado largo de community --match-url
    dt4 = parse_kickoff_utc(kickoff="Monday, 23 Nov 2026, 20:00")
    assert dt4 is not None and to_utc_iso(dt4) == "2026-11-23T20:00:00Z"


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
# 3. Curación, alcance de ligas y deduplicación
# ---------------------------------------------------------------------------
def test_league_scope_blocks_minor_leagues():
    assert resolve_allowed_league("Premier League", "football", "Inglaterra") == ("football", "Premier League")
    assert resolve_allowed_league("Premier League", "football", "Egipto") is None
    assert resolve_allowed_league("Süper Lig", "football", "Turquía") is None
    assert resolve_allowed_league("NBA", "basketball", "Estados Unidos") == ("basketball", "NBA")


def test_curate_real_phase1_basketball_sample():
    sample_path = SAMPLES_DIR / "community_basketball.json"
    if not sample_path.exists():
        pytest.skip("Sample de Fase 1 no disponible en este entorno")

    records = json.loads(sample_path.read_text(encoding="utf-8"))
    picks = curate_community_top_records(records)
    # Debe filtrar picks NBA con >= 70% de consenso (ej. Miami Heat 89% @ 1.53)
    assert len(picks) >= 1
    assert all(p.match.league == "NBA" for p in picks)
    assert all((p.consensus_pct or 0) >= 70 for p in picks)
    assert any("Miami Heat" in p.pick_label_es for p in picks)


def test_merge_duplicates_boosts_confidence_and_caps_at_8():
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
        supporting_sources=["Consenso Comunidad"],
    )
    p_tip = CuratedPrediction(
        match=match,
        source_type="tipster",
        source_name="BLAPRO",
        market_raw="1X2",
        pick_raw="Home",
        pick_label_es="Gana Club América",
        odds=1.88,
        consensus_pct=82,
        vote_breakdown=None,
        confidence_rank=8,
        supporting_sources=["BLAPRO"],
    )

    merged = merge_and_select_daily_picks([p_comm, p_tip])
    assert len(merged) == 1
    assert merged[0].source_type == "hybrid"
    assert merged[0].confidence_rank == 9
    assert merged[0].odds == 1.88


def test_curate_match_vote_record_threshold():
    vote_rec = {
        "mode": "match",
        "match_url": "https://www.cuotasahora.com/football/h2h/a/b/#CSnuq6U8",
        "event_id": "CSnuq6U8",
        "home_team": "Brentford",
        "away_team": "Everton",
        "kickoff": "Monday, 23 Nov 2026, 20:00",
        "is_prematch": True,
        "markets": [
            {
                "market": "1X2",
                "outcomes": [
                    {"outcome": "1", "votes_pct": 78},
                    {"outcome": "X", "votes_pct": 12},
                    {"outcome": "2", "votes_pct": 10},
                ],
            }
        ],
    }
    pick = curate_match_vote_record(
        vote_rec,
        league_name="Premier League",
        sport="football",
        odds_by_outcome={"1": 1.95, "X": 3.5, "2": 3.8},
    )
    assert pick is not None
    assert pick.pick_label_es == "Gana Brentford"
    assert pick.consensus_pct == 78


def test_curate_tipster_profile_skips_finished_and_low_winrate():
    profile = {
        "username": "PRO_TIPSTER",
        "privacy": "public",
        "scraped_at": "2026-11-22T12:00:00+00:00",
        "predictions": [
            {
                "kickoff": "2026-11-23T20:00",
                "market": "1X2",
                "home_team": "Arsenal",
                "away_team": "Chelsea",
                "score": None,
                "pick_odds": 1.80,
                "outcomes": [
                    {"odds": 1.80, "community_pct": 75, "picked": True},
                    {"odds": 3.60, "community_pct": 15, "picked": False},
                    {"odds": 4.20, "community_pct": 10, "picked": False},
                ],
                "match_url": "https://www.oddsportal.com/football/h2h/a/b/#FUTURE01:1X2;2",
            },
            {
                "kickoff": "2026-11-21T20:00",
                "market": "1X2",
                "home_team": "Liverpool",
                "away_team": "Man Utd",
                "score": "4-0",
                "pick_odds": 1.75,
                "outcomes": [
                    {"odds": 1.75, "community_pct": 80, "picked": True},
                    {"odds": 3.90, "community_pct": 10, "picked": False},
                    {"odds": 4.10, "community_pct": 10, "picked": False},
                ],
                "match_url": "https://www.oddsportal.com/football/h2h/c/d/#PAST0001:1X2;2",
            },
        ],
    }
    now = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    assert curate_tipster_profile(profile, tipster_win_rate=52.0, now_utc=now) == []
    picks = curate_tipster_profile(profile, tipster_win_rate=64.0, now_utc=now)
    assert len(picks) == 1
    assert picks[0].match.id == "FUTURE01"
    assert picks[0].pick_label_es == "Gana Arsenal"


# ---------------------------------------------------------------------------
# 4. Motor de calificación automática (Grading) y casos borde críticos
# ---------------------------------------------------------------------------
def test_grade_football_standard_markets():
    m = MatchOutcome(sport="football", status="finished", home_score=2, away_score=1, partial_results="(1:0, 1:1)")
    assert grade_prediction("1X2", "Home", m) == "won"
    assert grade_prediction("1X2", "Draw", m) == "lost"
    assert grade_prediction("1X2", "Away", m) == "lost"
    assert grade_prediction("Over/Under 2.5", "Over 2.5", m) == "won"
    assert grade_prediction("Over/Under 2.5", "Under 2.5", m) == "lost"
    assert grade_prediction("BTTS", "Yes", m) == "won"
    assert grade_prediction("BTTS", "No", m) == "lost"
    assert grade_prediction("Double Chance", "1X", m) == "won"
    assert grade_prediction("Double Chance", "X2", m) == "lost"


def test_grade_football_extra_time_and_penalties_uses_90_min():
    # Partido terminó 1-1 en 90' y local ganó en penales (OddsPortal reporta 2-1 con 4 parciales)
    m = MatchOutcome(
        sport="football",
        status="finished",
        home_score=2,
        away_score=1,
        partial_results="(0:1, 1:0, 0:0, 4:3)",
    )
    assert grade_prediction("1X2", "Home", m) == "lost"
    assert grade_prediction("1X2", "Draw", m) == "won"
    assert grade_prediction("Moneyline", "Home", m) == "lost"
    assert grade_prediction("Draw No Bet", "Home", m) == "void"


def test_grade_nba_includes_overtime():
    m = MatchOutcome(
        sport="basketball",
        status="finished",
        home_score=118,
        away_score=114,
        partial_results="(28:25, 24:27, 26:28, 28:26, 12:8)",
    )
    assert grade_prediction("Moneyline", "Home", m) == "won"
    assert grade_prediction("Moneyline", "Away", m) == "lost"
    assert grade_prediction("Over/Under 225.5", "Over 225.5", m) == "won"


def test_grade_edge_cases_push_and_postponed():
    # Línea entera Over/Under 2.0 con 2 goles -> void (reembolso)
    m_push = MatchOutcome(sport="football", status="finished", home_score=1, away_score=1)
    assert grade_prediction("Over/Under 2.0", "Over 2.0", m_push) == "void"
    assert grade_prediction("Draw No Bet", "Home", m_push) == "void"

    # Partido pospuesto o cancelado -> void inmediato
    m_post = MatchOutcome(sport="football", status="postponed", home_score=None, away_score=None)
    assert grade_prediction("1X2", "Home", m_post) == "void"

    m_canc = MatchOutcome(sport="basketball", status="cancelled", home_score=None, away_score=None)
    assert grade_prediction("Moneyline", "Away", m_canc) == "void"


def test_calculate_tipster_stats_excludes_void_and_pending():
    tracked, won, rate = calculate_tipster_stats(["won", "won", "lost", "void", "pending"])
    assert (tracked, won, rate) == (3, 2, 66.67)
