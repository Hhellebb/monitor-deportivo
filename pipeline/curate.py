"""Motor de curación, filtrado, deduplicación y ranking diario de pronósticos."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pipeline.config import (
    IDEAL_ODDS_MAX,
    IDEAL_ODDS_MIN,
    MAX_DAILY_PICKS,
    MIN_COMMUNITY_CONSENSUS_PCT,
    MIN_TIPSTER_WIN_RATE_PCT,
    REFERENCE_BOOKMAKER,
    TARGET_LEAGUES,
)
from pipeline.translator import normalize_and_translate
from pipeline.utils import extract_event_id, normalize_match_url, parse_kickoff_utc, to_utc_iso

# Alias aceptados para las 5 ligas objetivo: NBA, NFL, Bundesliga, LaLiga y Liga MX
_ALLOWED_LEAGUE_ALIASES: dict[str, tuple[str, str]] = {
    "liga mx": ("football", "Liga MX"),
    "mexico-liga-mx": ("football", "Liga MX"),
    "laliga": ("football", "LaLiga"),
    "la liga": ("football", "LaLiga"),
    "laliga ea sports": ("football", "LaLiga"),
    "spain-laliga": ("football", "LaLiga"),
    "bundesliga": ("football", "Bundesliga"),
    "germany-bundesliga": ("football", "Bundesliga"),
    "nba": ("basketball", "NBA"),
    "nfl": ("american-football", "NFL"),
}


@dataclass
class CuratedMatch:
    id: str
    external_url: str
    sport: str
    league: str
    home_team: str
    away_team: str
    start_time: str  # UTC ISO-8601
    status: str = "pending"
    home_form: str | None = None
    away_form: str | None = None

    def to_db_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": self.id,
            "external_url": self.external_url,
            "sport": self.sport,
            "league": self.league,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "start_time": self.start_time,
            "status": self.status,
        }
        if self.home_form:
            row["home_form"] = self.home_form
        if self.away_form:
            row["away_form"] = self.away_form
        return row


@dataclass
class CuratedPrediction:
    match: CuratedMatch
    source_type: str  # 'community', 'tipster', 'hybrid'
    source_name: str
    market_raw: str
    pick_raw: str
    pick_label_es: str
    odds: float
    consensus_pct: int | None
    vote_breakdown: list[dict[str, Any]] | None
    confidence_rank: int
    bookmaker: str = REFERENCE_BOOKMAKER
    short_reason: str | None = None
    supporting_sources: list[str] = field(default_factory=list)

    def to_db_row(self) -> dict[str, Any]:
        return {
            "match_id": self.match.id,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "market_raw": self.market_raw,
            "pick_raw": self.pick_raw,
            "pick_label_es": self.pick_label_es,
            "odds": round(self.odds, 2),
            "bookmaker": self.bookmaker,
            "consensus_pct": self.consensus_pct,
            "vote_breakdown": self.vote_breakdown,
            "short_reason": self.short_reason,
            "confidence_rank": self.confidence_rank,
            "result": "pending",
        }


def resolve_allowed_league(
    league_name: str | None,
    sport: str | None = None,
    country: str | None = None,
) -> tuple[str, str] | None:
    """Devuelve (sport_canónico, league_name_limpio) si la liga pertenece a las 5 ligas objetivo.

    Descarta ligas menores u homónimas de otros países (ej. Bundesliga de Austria).
    """
    if not league_name:
        return None

    key = league_name.strip().lower()
    if key not in _ALLOWED_LEAGUE_ALIASES:
        return None

    canonical_sport, clean_name = _ALLOWED_LEAGUE_ALIASES[key]

    if clean_name == "Bundesliga" and country:
        c_low = country.strip().lower()
        if c_low not in ("germany", "alemania"):
            return None

    if clean_name == "Liga MX" and country:
        c_low = country.strip().lower()
        if c_low not in ("mexico", "méxico"):
            return None

    if clean_name == "LaLiga" and country:
        c_low = country.strip().lower()
        if c_low not in ("spain", "españa"):
            return None

    if sport:
        s_low = sport.strip().lower()
        if s_low == "soccer":
            s_low = "football"
        if s_low != canonical_sport:
            return None

    return canonical_sport, clean_name


def compute_confidence_rank(
    odds: float,
    consensus_pct: int | None = None,
    tipster_win_rate: float | None = None,
    agreement_count: int = 1,
) -> int:
    """Calcula confidence_rank en escala 1..10 combinando consenso, rango de cuota y confluencia."""
    score = 5.0

    if consensus_pct is not None:
        if consensus_pct >= 90:
            score += 3.0
        elif consensus_pct >= 80:
            score += 2.2
        elif consensus_pct >= MIN_COMMUNITY_CONSENSUS_PCT:
            score += 1.2
        else:
            score -= 1.0

    if tipster_win_rate is not None:
        if tipster_win_rate >= 68:
            score += 2.2
        elif tipster_win_rate >= 62:
            score += 1.5
        elif tipster_win_rate >= MIN_TIPSTER_WIN_RATE_PCT:
            score += 0.8

    if IDEAL_ODDS_MIN <= odds <= IDEAL_ODDS_MAX:
        score += 1.5
    elif 1.28 <= odds < IDEAL_ODDS_MIN or IDEAL_ODDS_MAX < odds <= 2.60:
        score += 0.6
    else:
        score -= 1.0

    if agreement_count > 1:
        score += min(2.0, (agreement_count - 1) * 1.2)

    return max(1, min(10, int(round(score))))


def select_reference_odds(
    market_rows: list[dict[str, Any]],
    outcome_key: str,
    preferred_bookmaker: str = REFERENCE_BOOKMAKER,
) -> tuple[float | None, str]:
    """Extrae la cuota de `preferred_bookmaker` (bet365) para `outcome_key`.

    Si `bet365` no aparece o tiene el outcome bloqueado en ese partido/espejo,
    hace fallback al mejor momio disponible e informa el nombre real de la casa usada.
    """
    pref_low = preferred_bookmaker.strip().lower()
    fallback_val: float | None = None
    fallback_bookie = "Referencia mercado"

    for row in market_rows:
        blocked = set(row.get("blocked_outcomes") or [])
        if outcome_key in blocked or outcome_key not in row:
            continue
        try:
            val = float(row[outcome_key])
        except (TypeError, ValueError):
            continue
        if val <= 1.0:
            continue

        bname = str(row.get("bookmaker_name") or "").strip()
        if bname.lower() == pref_low:
            return val, bname

        if fallback_val is None or val > fallback_val:
            fallback_val = val
            fallback_bookie = bname or "Referencia mercado"

    return fallback_val, fallback_bookie


def curate_community_top_records(
    records: list[dict[str, Any]],
    *,
    strict_league_filter: bool = True,
    min_consensus_pct: int = MIN_COMMUNITY_CONSENSUS_PCT,
) -> list[CuratedPrediction]:
    """Procesa registros emitidos por `oddsharvester community --sport <sport>`."""
    curated: list[CuratedPrediction] = []

    for rec in records:
        sport = rec.get("sport", "football")
        league_raw = rec.get("league")
        country = rec.get("country")

        resolved = resolve_allowed_league(league_raw, sport=sport, country=country)
        if strict_league_filter and resolved is None:
            continue

        canonical_sport, clean_league = resolved if resolved else (sport, str(league_raw or "General"))
        match_url = rec.get("match_url") or ""
        if not match_url:
            continue

        kickoff_dt = parse_kickoff_utc(
            kickoff=rec.get("kickoff"),
            kickoff_text=rec.get("kickoff_text"),
            scraped_at=rec.get("scraped_at"),
        )
        if kickoff_dt is None:
            continue

        votes = rec.get("community_votes_pct") or []
        odds_list = rec.get("odds") or []
        if not votes or not odds_list:
            continue

        best_vote = max(votes, key=lambda v: int(v.get("pct") or 0))
        top_outcome = str(best_vote.get("outcome", "")).strip()
        top_pct = int(best_vote.get("pct") or 0)
        if top_pct < min_consensus_pct:
            continue

        matched_odds = next(
            (float(o["odds"]) for o in odds_list if str(o.get("outcome", "")).strip() == top_outcome and o.get("odds")),
            None,
        )
        if matched_odds is None or matched_odds <= 1.0:
            continue

        home_team = str(rec.get("home_team") or "").strip()
        away_team = str(rec.get("away_team") or "").strip()
        market_text = str(rec.get("market") or "").strip()
        if not home_team or not away_team:
            continue

        translated = normalize_and_translate(
            market=market_text,
            outcome=top_outcome,
            home_team=home_team,
            away_team=away_team,
            sport=canonical_sport,
        )
        if translated is None:
            continue

        match_obj = CuratedMatch(
            id=extract_event_id(match_url),
            external_url=normalize_match_url(match_url),
            sport=canonical_sport,
            league=clean_league,
            home_team=home_team,
            away_team=away_team,
            start_time=to_utc_iso(kickoff_dt),
        )

        rank = compute_confidence_rank(odds=matched_odds, consensus_pct=top_pct)
        curated.append(
            CuratedPrediction(
                match=match_obj,
                source_type="community",
                source_name="Consenso Comunidad",
                market_raw=translated.market_raw,
                pick_raw=translated.pick_raw,
                pick_label_es=translated.pick_label_es,
                odds=matched_odds,
                consensus_pct=top_pct,
                vote_breakdown=votes,
                confidence_rank=rank,
                bookmaker="OddsPortal (Comunidad)",
                supporting_sources=["Consenso Comunidad"],
            )
        )

    return curated


def curate_match_vote_record(
    vote_record: dict[str, Any],
    *,
    league_name: str,
    sport: str,
    odds_by_outcome: dict[str, tuple[float, str]],
    min_consensus_pct: int = MIN_COMMUNITY_CONSENSUS_PCT,
) -> CuratedPrediction | None:
    """Procesa `oddsharvester community --match-url` combinado con momios (bet365/fallback) de `upcoming`."""
    if not vote_record.get("is_prematch", True):
        return None

    markets = vote_record.get("markets") or []
    if not markets:
        return None

    first_market = markets[0]
    outcomes = first_market.get("outcomes") or []
    if not outcomes:
        return None

    best_vote = max(outcomes, key=lambda o: int(o.get("votes_pct") or 0))
    top_outcome = str(best_vote.get("outcome", "")).strip()
    top_pct = int(best_vote.get("votes_pct") or 0)
    if top_pct < min_consensus_pct:
        return None

    odds_pair = odds_by_outcome.get(top_outcome)
    if not odds_pair:
        return None
    matched_odds, bookmaker = odds_pair
    if matched_odds <= 1.0:
        return None

    kickoff_dt = parse_kickoff_utc(
        kickoff=vote_record.get("kickoff"),
        scraped_at=vote_record.get("scraped_at"),
    )
    if kickoff_dt is None:
        return None

    home_team = str(vote_record.get("home_team") or "").strip()
    away_team = str(vote_record.get("away_team") or "").strip()
    market_text = str(first_market.get("market") or "").strip()
    translated = normalize_and_translate(
        market=market_text,
        outcome=top_outcome,
        home_team=home_team,
        away_team=away_team,
        sport=sport,
    )
    if translated is None:
        return None

    match_url = vote_record.get("match_url") or ""
    event_id = vote_record.get("event_id") or extract_event_id(match_url)
    match_obj = CuratedMatch(
        id=event_id,
        external_url=normalize_match_url(match_url),
        sport=sport,
        league=league_name,
        home_team=home_team,
        away_team=away_team,
        start_time=to_utc_iso(kickoff_dt),
    )

    breakdown = [{"outcome": o.get("outcome"), "pct": int(o.get("votes_pct") or 0)} for o in outcomes]
    rank = compute_confidence_rank(odds=matched_odds, consensus_pct=top_pct)
    return CuratedPrediction(
        match=match_obj,
        source_type="community",
        source_name="Consenso Comunidad",
        market_raw=translated.market_raw,
        pick_raw=translated.pick_raw,
        pick_label_es=translated.pick_label_es,
        odds=matched_odds,
        consensus_pct=top_pct,
        vote_breakdown=breakdown,
        confidence_rank=rank,
        bookmaker=bookmaker,
        supporting_sources=["Consenso Comunidad"],
    )


def curate_football_multi_market_picks(
    match_record: dict[str, Any],
    *,
    league_name: str,
    home_team_stats: dict[str, Any] | None = None,
    away_team_stats: dict[str, Any] | None = None,
    vote_breakdown_1x2: list[dict[str, Any]] | None = None,
) -> list[CuratedPrediction]:
    """Evalúa mercados secundarios de fútbol (`Over/Under 2.5`, `BTTS`, `Double Chance`)
    respaldados por estadísticas reales de `oddsharvester team` y cuotas de `bet365` (o fallback).
    """
    match_url = str(match_record.get("match_link") or "")
    home_team = str(match_record.get("home_team") or "").strip()
    away_team = str(match_record.get("away_team") or "").strip()
    kickoff_dt = parse_kickoff_utc(match_date=match_record.get("match_date"))
    if not match_url or not home_team or not away_team or kickoff_dt is None:
        return []

    match_obj = CuratedMatch(
        id=extract_event_id(match_url),
        external_url=normalize_match_url(match_url),
        sport="football",
        league=league_name,
        home_team=home_team,
        away_team=away_team,
        start_time=to_utc_iso(kickoff_dt),
        home_form=home_team_stats.get("form") if home_team_stats else None,
        away_form=away_team_stats.get("form") if away_team_stats else None,
    )

    picks: list[CuratedPrediction] = []

    # 1. Doble Oportunidad (1X o X2) si el respaldo combinado en 1X2 supera >= 78% y la cuota está en [1.30, 1.85]
    dc_rows = match_record.get("double_chance_market") or []
    if dc_rows and vote_breakdown_1x2:
        pct_map = {str(v.get("outcome", "")).strip(): int(v.get("pct") or 0) for v in vote_breakdown_1x2}
        home_or_draw = pct_map.get("1", 0) + pct_map.get("X", 0)
        away_or_draw = pct_map.get("2", 0) + pct_map.get("X", 0)
        for dc_key, combined_pct in (("1X", home_or_draw), ("X2", away_or_draw)):
            if combined_pct < 78:
                continue
            odds_val, bookie = select_reference_odds(dc_rows, dc_key)
            if odds_val and 1.30 <= odds_val <= 1.85:
                tr = normalize_and_translate("Double Chance", dc_key, home_team, away_team, sport="football")
                if tr:
                    picks.append(
                        CuratedPrediction(
                            match=match_obj,
                            source_type="community",
                            source_name="Consenso Comunidad",
                            market_raw=tr.market_raw,
                            pick_raw=tr.pick_raw,
                            pick_label_es=tr.pick_label_es,
                            odds=odds_val,
                            consensus_pct=combined_pct,
                            vote_breakdown=vote_breakdown_1x2,
                            confidence_rank=compute_confidence_rank(odds_val, consensus_pct=combined_pct),
                            bookmaker=bookie,
                            supporting_sources=["Consenso Comunidad"],
                        )
                    )

    # 2. BTTS (Ambos Equipos Anotan) si ambos equipos promedian >= 65% de BTTS en sus últimos 6 juegos
    btts_rows = match_record.get("btts_market") or []
    if btts_rows and home_team_stats and away_team_stats:
        h_btts = home_team_stats.get("btts_pct")
        a_btts = away_team_stats.get("btts_pct")
        if h_btts is not None and a_btts is not None:
            avg_btts = int(round((float(h_btts) + float(a_btts)) / 2.0))
            if avg_btts >= 65:
                odds_val, bookie = select_reference_odds(btts_rows, "btts_yes")
                if odds_val and 1.35 <= odds_val <= 2.25:
                    tr = normalize_and_translate("BTTS", "Yes", home_team, away_team, sport="football")
                    if tr:
                        picks.append(
                            CuratedPrediction(
                                match=match_obj,
                                source_type="community",
                                source_name="Tendencia Equipos",
                                market_raw=tr.market_raw,
                                pick_raw=tr.pick_raw,
                                pick_label_es=tr.pick_label_es,
                                odds=odds_val,
                                consensus_pct=avg_btts,
                                vote_breakdown=None,
                                confidence_rank=compute_confidence_rank(odds_val, consensus_pct=avg_btts),
                                bookmaker=bookie,
                                supporting_sources=["Tendencia Equipos"],
                            )
                        )

    # 3. Over/Under 2.5 goles (OddsHarvester usa 'odds_over' / 'odds_under' y submarket_name '+2.5')
    ou_rows_all = match_record.get("over_under_2_5_market") or []
    ou_rows = _filter_over_under_line(ou_rows_all, "2.5")
    if ou_rows and home_team_stats and away_team_stats:
        h_o25 = home_team_stats.get("over_2_5_pct")
        a_o25 = away_team_stats.get("over_2_5_pct")
        if h_o25 is not None and a_o25 is not None:
            avg_o25 = int(round((float(h_o25) + float(a_o25)) / 2.0))
            if avg_o25 >= 67:
                odds_val, bookie = select_reference_odds(ou_rows, "odds_over")
                if odds_val and 1.35 <= odds_val <= 2.25:
                    tr = normalize_and_translate("Over/Under 2.5", "Over 2.5", home_team, away_team, sport="football")
                    if tr:
                        picks.append(
                            CuratedPrediction(
                                match=match_obj,
                                source_type="community",
                                source_name="Tendencia Equipos",
                                market_raw=tr.market_raw,
                                pick_raw=tr.pick_raw,
                                pick_label_es=tr.pick_label_es,
                                odds=odds_val,
                                consensus_pct=avg_o25,
                                vote_breakdown=None,
                                confidence_rank=compute_confidence_rank(odds_val, consensus_pct=avg_o25),
                                bookmaker=bookie,
                                supporting_sources=["Tendencia Equipos"],
                            )
                        )
            elif avg_o25 <= 33:
                under_pct = 100 - avg_o25
                odds_val, bookie = select_reference_odds(ou_rows, "odds_under")
                if odds_val and 1.35 <= odds_val <= 2.25:
                    tr = normalize_and_translate("Over/Under 2.5", "Under 2.5", home_team, away_team, sport="football")
                    if tr:
                        picks.append(
                            CuratedPrediction(
                                match=match_obj,
                                source_type="community",
                                source_name="Tendencia Equipos",
                                market_raw=tr.market_raw,
                                pick_raw=tr.pick_raw,
                                pick_label_es=tr.pick_label_es,
                                odds=odds_val,
                                consensus_pct=under_pct,
                                vote_breakdown=None,
                                confidence_rank=compute_confidence_rank(odds_val, consensus_pct=under_pct),
                                bookmaker=bookie,
                                supporting_sources=["Tendencia Equipos"],
                            )
                        )

    return picks


def _filter_over_under_line(rows: list[dict[str, Any]], target_line: str) -> list[dict[str, Any]]:
    """Filtra filas de Over/Under a la línea exacta (ej. '2.5') cuando OddsHarvester
    devuelve múltiples líneas en modo passive/preview ('+0.5', '+1.5', '+2.5', ...).
    """
    if not rows:
        return []
    matched = [
        r
        for r in rows
        if target_line in str(r.get("submarket_name") or "")
        and f"{target_line}5" not in str(r.get("submarket_name") or "")
    ]
    return matched if matched else rows


def curate_tipster_profile(
    profile_record: dict[str, Any],
    *,
    tipster_win_rate: float,
    tipster_active: bool = True,
    now_utc: datetime | None = None,
) -> list[CuratedPrediction]:
    """Extrae picks futuros válidos del perfil de un tipster (`oddsharvester community --user`)."""
    if not tipster_active or tipster_win_rate < MIN_TIPSTER_WIN_RATE_PCT:
        return []
    if profile_record.get("privacy") != "public":
        return []

    username = str(profile_record.get("username") or "").strip()
    if not username:
        return []

    ref_now = now_utc or datetime.now(UTC)
    curated: list[CuratedPrediction] = []

    for pred in profile_record.get("predictions") or []:
        if pred.get("score"):
            continue

        kickoff_dt = parse_kickoff_utc(
            kickoff=pred.get("kickoff"),
            kickoff_text=pred.get("kickoff_text"),
            scraped_at=profile_record.get("scraped_at"),
        )
        if kickoff_dt is None or kickoff_dt <= ref_now:
            continue

        match_url = str(pred.get("match_url") or "")
        sport = _infer_sport_from_url(match_url)
        if sport not in {lg.sport for lg in TARGET_LEAGUES}:
            continue

        outcomes = pred.get("outcomes") or []
        picked_idx = next((i for i, o in enumerate(outcomes) if o.get("picked")), None)
        if picked_idx is None:
            continue

        market_text = str(pred.get("market") or "").strip()
        outcome_token = _positional_outcome_token(market_text, picked_idx, len(outcomes))
        if outcome_token is None:
            continue

        home_team = str(pred.get("home_team") or "").strip()
        away_team = str(pred.get("away_team") or "").strip()
        translated = normalize_and_translate(
            market=market_text,
            outcome=outcome_token,
            home_team=home_team,
            away_team=away_team,
            sport=sport,
        )
        if translated is None:
            continue

        pick_odds = pred.get("pick_odds") or outcomes[picked_idx].get("odds")
        if not pick_odds or float(pick_odds) <= 1.0:
            continue
        odds_val = float(pick_odds)
        comm_pct = outcomes[picked_idx].get("community_pct")
        comm_pct_int = int(comm_pct) if comm_pct is not None else None

        match_obj = CuratedMatch(
            id=extract_event_id(match_url),
            external_url=normalize_match_url(match_url),
            sport=sport,
            league="Destacado Tipster",
            home_team=home_team,
            away_team=away_team,
            start_time=to_utc_iso(kickoff_dt),
        )

        rank = compute_confidence_rank(
            odds=odds_val,
            consensus_pct=comm_pct_int,
            tipster_win_rate=tipster_win_rate,
        )
        curated.append(
            CuratedPrediction(
                match=match_obj,
                source_type="tipster",
                source_name=username,
                market_raw=translated.market_raw,
                pick_raw=translated.pick_raw,
                pick_label_es=translated.pick_label_es,
                odds=odds_val,
                consensus_pct=comm_pct_int,
                vote_breakdown=None,
                confidence_rank=rank,
                bookmaker="OddsPortal (Tipster)",
                supporting_sources=[username],
            )
        )

    return curated


def merge_and_select_daily_picks(
    candidates: list[CuratedPrediction],
    *,
    max_picks: int = MAX_DAILY_PICKS,
) -> list[CuratedPrediction]:
    """Unifica pronósticos coincidentes sobre el mismo partido+mercado (sin duplicar
    mismo partido y mercado), refuerza su confianza y selecciona hasta `max_picks`.
    """
    grouped: dict[tuple[str, str], CuratedPrediction] = {}

    for cand in candidates:
        key = (cand.match.id, cand.market_raw)
        if key not in grouped:
            grouped[key] = cand
            continue

        existing = grouped[key]
        # Si es el mismo pick, fusionar y aumentar confianza
        if existing.pick_raw == cand.pick_raw:
            merged_sources = list(dict.fromkeys(existing.supporting_sources + cand.supporting_sources))
            types = {existing.source_type, cand.source_type}
            if "hybrid" in types or ("community" in types and "tipster" in types):
                new_source_type = "hybrid"
                tipsters = [s for s in merged_sources if s != "Consenso Comunidad"]
                new_source_name = f"Comunidad + {', '.join(tipsters)}" if tipsters else "Consenso Comunidad"
            else:
                new_source_type = existing.source_type
                new_source_name = ", ".join(merged_sources)

            best_consensus = max(
                [c for c in (existing.consensus_pct, cand.consensus_pct) if c is not None],
                default=None,
            )
            # Priorizar cuota de bet365 si una de las dos viene de bet365
            if cand.bookmaker.lower() == REFERENCE_BOOKMAKER and existing.bookmaker.lower() != REFERENCE_BOOKMAKER:
                chosen_odds, chosen_bookie = cand.odds, cand.bookmaker
            else:
                chosen_odds, chosen_bookie = max(existing.odds, cand.odds), existing.bookmaker

            if existing.match.league == "Destacado Tipster" and cand.match.league != "Destacado Tipster":
                existing.match.league = cand.match.league
            if not existing.match.home_form and cand.match.home_form:
                existing.match.home_form = cand.match.home_form
            if not existing.match.away_form and cand.match.away_form:
                existing.match.away_form = cand.match.away_form

            boosted_rank = min(
                10,
                max(existing.confidence_rank, cand.confidence_rank)
                + (len(merged_sources) - len(existing.supporting_sources)),
            )
            grouped[key] = CuratedPrediction(
                match=existing.match,
                source_type=new_source_type,
                source_name=new_source_name,
                market_raw=existing.market_raw,
                pick_raw=existing.pick_raw,
                pick_label_es=existing.pick_label_es,
                odds=chosen_odds,
                consensus_pct=best_consensus,
                vote_breakdown=existing.vote_breakdown or cand.vote_breakdown,
                confidence_rank=boosted_rank,
                bookmaker=chosen_bookie,
                short_reason=existing.short_reason or cand.short_reason,
                supporting_sources=merged_sources,
            )
        elif cand.confidence_rank > existing.confidence_rank:
            # Mismo partido y mercado pero picks opuestos -> conservar el de mayor confianza
            grouped[key] = cand

    def _sort_key(p: CuratedPrediction) -> tuple[int, int, int, str]:
        in_ideal_odds = 1 if IDEAL_ODDS_MIN <= p.odds <= IDEAL_ODDS_MAX else 0
        return (
            -p.confidence_rank,
            -in_ideal_odds,
            -(p.consensus_pct or 0),
            p.match.start_time,
        )

    ranked = sorted(grouped.values(), key=_sort_key)
    return ranked[:max_picks]


def _infer_sport_from_url(url: str) -> str:
    parts = [p for p in url.split("/") if p]
    for idx, part in enumerate(parts):
        if "oddsportal" in part or "cuotasahora" in part:
            if idx + 1 < len(parts):
                return parts[idx + 1].lower()
    return ""


def _positional_outcome_token(market: str, idx: int, total: int) -> str | None:
    m_low = market.lower()
    if m_low == "1x2" and total == 3:
        return ("1", "X", "2")[idx]
    if any(k in m_low for k in ("h/a", "home/away", "moneyline", "winner", "dnb", "draw no bet")) and total == 2:
        return ("1", "2")[idx]
    if any(k in m_low for k in ("btts", "both teams", "bts")) and total == 2:
        return ("Yes", "No")[idx]
    if any(k in m_low for k in ("over/under", "o/u", "más/menos", "mas/menos")) and total == 2:
        return ("Over", "Under")[idx]
    if any(k in m_low for k in ("double chance", "doble oportunidad", "dc")) and total == 3:
        return ("1X", "12", "X2")[idx]
    return None
