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
    TARGET_LEAGUES,
)
from pipeline.translator import normalize_and_translate
from pipeline.utils import extract_event_id, normalize_match_url, parse_kickoff_utc, to_utc_iso

# Alias aceptados para filtrar ligas relevantes (inglés y español)
_ALLOWED_LEAGUE_ALIASES: dict[str, tuple[str, str]] = {
    "liga mx": ("football", "Liga MX"),
    "mexico-liga-mx": ("football", "Liga MX"),
    "premier league": ("football", "Premier League"),
    "england-premier-league": ("football", "Premier League"),
    "laliga": ("football", "LaLiga"),
    "la liga": ("football", "LaLiga"),
    "laliga ea sports": ("football", "LaLiga"),
    "spain-laliga": ("football", "LaLiga"),
    "champions league": ("football", "Champions League"),
    "champions-league": ("football", "Champions League"),
    "nba": ("basketball", "NBA"),
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

    def to_db_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "external_url": self.external_url,
            "sport": self.sport,
            "league": self.league,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "start_time": self.start_time,
            "status": self.status,
        }


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
    """Devuelve (sport_canónico, league_name_limpio) si la liga está dentro del alcance permitido.

    Devuelve None para ligas menores o fuera de alcance (ej. Premier League de Egipto/Ucrania).
    """
    if not league_name:
        return None

    key = league_name.strip().lower()
    if key not in _ALLOWED_LEAGUE_ALIASES:
        return None

    canonical_sport, clean_name = _ALLOWED_LEAGUE_ALIASES[key]

    # Evitar falsos positivos como 'Premier League' de otros países (ej. Egipto, Rusia, Ucrania)
    if clean_name == "Premier League" and country:
        c_low = country.strip().lower()
        if c_low not in ("england", "inglaterra", "uk", "united kingdom"):
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
    """Calcula confidence_rank en escala 1..10 combinando consenso, rango de cuota ideal y confluencia."""
    score = 5.0

    # 1. Fuerza de consenso comunitario (70% -> +1.0, 85%+ -> +2.5, 95%+ -> +3.0)
    if consensus_pct is not None:
        if consensus_pct >= 90:
            score += 3.0
        elif consensus_pct >= 80:
            score += 2.2
        elif consensus_pct >= MIN_COMMUNITY_CONSENSUS_PCT:
            score += 1.2
        else:
            score -= 1.0

    # 2. Efectividad histórica de tipster (58% -> +1.0, 65%+ -> +2.0)
    if tipster_win_rate is not None:
        if tipster_win_rate >= 68:
            score += 2.2
        elif tipster_win_rate >= 62:
            score += 1.5
        elif tipster_win_rate >= MIN_TIPSTER_WIN_RATE_PCT:
            score += 0.8

    # 3. Ventana ideal de cuota (1.40 - 2.25)
    if IDEAL_ODDS_MIN <= odds <= IDEAL_ODDS_MAX:
        score += 1.5
    elif 1.25 <= odds < IDEAL_ODDS_MIN or IDEAL_ODDS_MAX < odds <= 2.60:
        score += 0.3
    else:
        score -= 1.0

    # 4. Bonus por coincidencia múltiple (comunidad + tipsters o varios tipsters)
    if agreement_count > 1:
        score += min(2.0, (agreement_count - 1) * 1.2)

    return max(1, min(10, int(round(score))))


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

        # Elegir el outcome con mayor porcentaje de votos comunitarios
        best_vote = max(votes, key=lambda v: int(v.get("pct") or 0))
        top_outcome = str(best_vote.get("outcome", "")).strip()
        top_pct = int(best_vote.get("pct") or 0)
        if top_pct < min_consensus_pct:
            continue

        # Buscar la cuota correspondiente a ese outcome
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
                supporting_sources=["Consenso Comunidad"],
            )
        )

    return curated


def curate_match_vote_record(
    vote_record: dict[str, Any],
    *,
    league_name: str,
    sport: str,
    odds_by_outcome: dict[str, float],
    min_consensus_pct: int = MIN_COMMUNITY_CONSENSUS_PCT,
) -> CuratedPrediction | None:
    """Procesa un registro de `oddsharvester community --match-url` combinado con momios de `upcoming`."""
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

    matched_odds = odds_by_outcome.get(top_outcome)
    if matched_odds is None or matched_odds <= 1.0:
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
        supporting_sources=["Consenso Comunidad"],
    )


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
        # Ignorar picks ya concluidos (tienen score)
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
                supporting_sources=[username],
            )
        )

    return curated


def merge_and_select_daily_picks(
    candidates: list[CuratedPrediction],
    *,
    max_picks: int = MAX_DAILY_PICKS,
) -> list[CuratedPrediction]:
    """Unifica pronósticos coincidentes sobre el mismo partido+mercado+selección
    incrementando su confianza, y selecciona hasta `max_picks` mejores picks diarios.
    """
    grouped: dict[tuple[str, str, str], CuratedPrediction] = {}

    for cand in candidates:
        key = (cand.match.id, cand.market_raw, cand.pick_raw)
        if key not in grouped:
            grouped[key] = cand
            continue

        existing = grouped[key]
        merged_sources = list(dict.fromkeys(existing.supporting_sources + cand.supporting_sources))

        # Determinar tipo de fuente unificado
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
        best_odds = max(existing.odds, cand.odds)
        best_breakdown = existing.vote_breakdown or cand.vote_breakdown

        # Preferir nombre de liga explícito sobre placeholder de tipster
        if existing.match.league == "Destacado Tipster" and cand.match.league != "Destacado Tipster":
            existing.match.league = cand.match.league

        boosted_rank = min(
            10,
            max(existing.confidence_rank, cand.confidence_rank) + (len(merged_sources) - len(existing.supporting_sources)),
        )
        grouped[key] = CuratedPrediction(
            match=existing.match,
            source_type=new_source_type,
            source_name=new_source_name,
            market_raw=existing.market_raw,
            pick_raw=existing.pick_raw,
            pick_label_es=existing.pick_label_es,
            odds=best_odds,
            consensus_pct=best_consensus,
            vote_breakdown=best_breakdown,
            confidence_rank=boosted_rank,
            short_reason=existing.short_reason or cand.short_reason,
            supporting_sources=merged_sources,
        )

    # Priorizar por confidence_rank DESC, ideal odds window, consensus_pct DESC, hora de inicio ASC
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
    # https://www.oddsportal.com/<sport>/...
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
