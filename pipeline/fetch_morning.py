"""Flujo matutino de recolección multi-mercado, curación, parlay diario y persistencia.

Ejecución local (sin escribir en BD):
    python -m pipeline.fetch_morning --dry-run

Ejecución productiva (GitHub Actions):
    python -m pipeline.fetch_morning
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from pipeline.ai_summary import generate_short_reason
from pipeline.config import (
    MAX_DAILY_PICKS,
    MIN_DAILY_PICKS,
    REFERENCE_BOOKMAKER,
    TARGET_LEAGUES,
    USER_TIMEZONE,
)
from pipeline.curate import (
    CuratedPrediction,
    curate_community_top_records,
    curate_football_multi_market_picks,
    curate_match_vote_record,
    curate_tipster_profile,
    merge_and_select_daily_picks,
    select_reference_odds,
)
from pipeline.db import MonitorRepository, get_supabase_admin_client
from pipeline.parlay import ParlayLegCandidate, build_daily_parlay
from pipeline.utils import (
    extract_event_id,
    extract_team_ids_from_url,
    normalize_match_url,
    parse_kickoff_utc,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("fetch_morning")


def _oddsharvester_exe() -> str:
    bin_dir = Path(sys.executable).parent
    for candidate in ("oddsharvester.exe", "oddsharvester"):
        p = bin_dir / candidate
        if p.exists():
            return str(p)
    return "oddsharvester"


def _run_oddsharvester(args: list[str], output_file: Path) -> list[dict[str, Any]]:
    base_url = os.environ.get("OH_BASE_URL", "").strip()
    cmd = [_oddsharvester_exe(), *args, "--timezone", "UTC", "-f", "json", "-o", str(output_file), "--headless"]
    if base_url:
        cmd.extend(["--base-url", base_url])

    logger.info("Ejecutando: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        logger.warning("OddsHarvester terminó con código %s: %s", proc.returncode, proc.stderr[-400:])
    if not output_file.exists():
        return []
    try:
        data = json.loads(output_file.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        logger.error("JSON inválido en %s", output_file)
        return []


def _extract_primary_odds_map(
    match_record: dict[str, Any],
    sport: str,
) -> dict[str, tuple[float, str]]:
    """Extrae momios (priorizando bet365, con fallback) por outcome ('1', 'X', '2')."""
    market_key = "1x2_market" if sport == "football" else "home_away_market"
    rows = match_record.get(market_key) or match_record.get("moneyline_market") or []
    result: dict[str, tuple[float, str]] = {}
    for outcome_key in ("1", "X", "2"):
        val, bookie = select_reference_odds(rows, outcome_key, preferred_bookmaker=REFERENCE_BOOKMAKER)
        if val is not None:
            result[outcome_key] = (val, bookie)
    return result


def _fetch_team_stats(team_ids: list[str], out_file: Path) -> dict[str, dict[str, Any]]:
    """Consulta `oddsharvester team` en lote para obtener racha y tendencias reales."""
    unique_ids = list(dict.fromkeys(tid for tid in team_ids if tid))
    if not unique_ids:
        return {}
    records = _run_oddsharvester(["team", "--team", ",".join(unique_ids)], out_file)
    by_id: dict[str, dict[str, Any]] = {}
    for rec in records:
        tid = str(rec.get("team_id") or "").strip()
        if tid:
            by_id[tid] = rec
    return by_id


def _match_team_stats_to_sides(
    home_team: str,
    away_team: str,
    match_url: str,
    stats_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Empareja estadísticas de `oddsharvester team` a equipo local y visitante usando list_name/name."""
    ids = extract_team_ids_from_url(match_url)
    h_low = home_team.strip().lower()
    a_low = away_team.strip().lower()
    home_stats: dict[str, Any] | None = None
    away_stats: dict[str, Any] | None = None

    for tid in ids:
        rec = stats_by_id.get(tid)
        if not rec:
            continue
        names = {
            str(rec.get("name") or "").strip().lower(),
            str(rec.get("list_name") or "").strip().lower(),
        }
        if h_low in names or any(n and (n in h_low or h_low in n) for n in names):
            home_stats = rec
        elif a_low in names or any(n and (n in a_low or a_low in n) for n in names):
            away_stats = rec

    return home_stats, away_stats


def collect_and_curate(
    *,
    active_tipsters: list[dict[str, Any]],
    horizon_hours: int = 48,
) -> tuple[list[CuratedPrediction], int]:
    """Estrategia híbrida multi-liga y multi-mercado:
    1. Top picks comunitarios por deporte (`football`, `basketball`, `american-football`).
    2. Perfiles de tipsters activos (`community --user`).
    3. Recolección directa de las 5 ligas objetivo (`Liga MX`, `LaLiga`, `Bundesliga`, `NBA`, `NFL`)
       con cuotas de referencia `bet365` (fallback automático), votos comunitarios y
       mercados secundarios de fútbol (`over_under_2_5`, `btts`, `double_chance`) apoyados en `team`.
    """
    candidates: list[CuratedPrediction] = []
    matches_evaluated = 0
    now_utc = datetime.now(UTC)
    max_start_utc = now_utc + timedelta(hours=horizon_hours)

    with tempfile.TemporaryDirectory(prefix="oh_morning_") as tmp:
        tmp_dir = Path(tmp)

        # 1. Top picks comunitarios por deporte activo
        sports = list(dict.fromkeys(lg.sport for lg in TARGET_LEAGUES))
        for sport in sports:
            out = tmp_dir / f"community_{sport}.json"
            records = _run_oddsharvester(["community", "-s", sport], out)
            matches_evaluated += len(records)
            for p in curate_community_top_records(records, strict_league_filter=True):
                dt = parse_kickoff_utc(kickoff=p.match.start_time)
                if dt and now_utc <= dt <= max_start_utc:
                    candidates.append(p)

        # 2. Tipsters activos registrados en Supabase
        for tip in active_tipsters:
            username = str(tip.get("username") or "").strip()
            win_rate = float(tip.get("win_rate") or 0.0)
            if not username:
                continue
            out = tmp_dir / f"tipster_{username}.json"
            records = _run_oddsharvester(["community", "--user", username], out)
            if records:
                matches_evaluated += len(records[0].get("predictions") or [])
                candidates.extend(
                    curate_tipster_profile(
                        records[0],
                        tipster_win_rate=win_rate,
                        tipster_active=True,
                        now_utc=now_utc,
                    )
                )

        # 3. Complementar en ligas objetivo con mercados múltiples + votos comunitarios + contexto de equipo
        prelim = merge_and_select_daily_picks(candidates, max_picks=MAX_DAILY_PICKS)
        if len(prelim) < MAX_DAILY_PICKS:
            seen_ids = {p.match.id for p in prelim}
            for league in TARGET_LEAGUES:
                if len(merge_and_select_daily_picks(candidates, max_picks=MAX_DAILY_PICKS)) >= MAX_DAILY_PICKS:
                    break

                links_out = tmp_dir / f"upcoming_{league.league_slug}.json"
                link_rows = _run_oddsharvester(
                    ["upcoming", "-s", league.sport, "-l", league.league_slug, "--links-only"],
                    links_out,
                )

                selected_links: list[str] = []
                for row in link_rows:
                    link = str(row.get("match_link") or "")
                    if not link:
                        continue
                    event_id = extract_event_id(link)
                    if event_id in seen_ids:
                        continue
                    kickoff_dt = parse_kickoff_utc(match_date=row.get("kickoff_utc"))
                    if kickoff_dt and kickoff_dt > max_start_utc:
                        continue
                    selected_links.append(normalize_match_url(link))
                    seen_ids.add(event_id)
                    if len(selected_links) >= 3:
                        break

                if not selected_links:
                    continue

                # Mercados a raspar: multi-mercado en fútbol, ganador en NBA/NFL
                markets_arg = (
                    "1x2,over_under_2_5,btts,double_chance"
                    if league.sport == "football"
                    else "home_away"
                )
                odds_out = tmp_dir / f"odds_{league.league_slug}.json"
                odds_args = ["upcoming", "-s", league.sport, "-m", markets_arg, "--preview-only"]
                for link in selected_links:
                    odds_args.extend(["--match-link", link])
                match_records = _run_oddsharvester(odds_args, odds_out)
                matches_evaluated += len(match_records)

                # Estadísticas de equipos para fútbol (racha + % Over 2.5 + % BTTS)
                team_stats_by_id: dict[str, dict[str, Any]] = {}
                if league.sport == "football" and match_records:
                    t_ids = [
                        tid
                        for mrec in match_records
                        for tid in extract_team_ids_from_url(str(mrec.get("match_link") or ""))
                    ]
                    team_stats_by_id = _fetch_team_stats(t_ids, tmp_dir / f"teams_{league.league_slug}.json")

                records_by_event = {
                    extract_event_id(str(mrec.get("match_link") or "")): mrec for mrec in match_records
                }

                for link in selected_links:
                    eid = extract_event_id(link)
                    mrec = records_by_event.get(eid)
                    if not mrec:
                        continue

                    odds_map = _extract_primary_odds_map(mrec, league.sport)
                    vote_out = tmp_dir / f"votes_{eid}.json"
                    vote_records = _run_oddsharvester(["community", "--match-url", link], vote_out)

                    vote_breakdown_1x2: list[dict[str, Any]] | None = None
                    if vote_records and odds_map:
                        vrec = vote_records[0]
                        markets = vrec.get("markets") or []
                        if markets:
                            vote_breakdown_1x2 = [
                                {"outcome": o.get("outcome"), "pct": int(o.get("votes_pct") or 0)}
                                for o in (markets[0].get("outcomes") or [])
                            ]
                        pick = curate_match_vote_record(
                            vrec,
                            league_name=league.league_name,
                            sport=league.sport,
                            odds_by_outcome=odds_map,
                        )
                        if pick is not None:
                            candidates.append(pick)

                    if league.sport == "football":
                        h_stats, a_stats = _match_team_stats_to_sides(
                            str(mrec.get("home_team") or ""),
                            str(mrec.get("away_team") or ""),
                            link,
                            team_stats_by_id,
                        )
                        candidates.extend(
                            curate_football_multi_market_picks(
                                mrec,
                                league_name=league.league_name,
                                home_team_stats=h_stats,
                                away_team_stats=a_stats,
                                vote_breakdown_1x2=vote_breakdown_1x2,
                            )
                        )

        final_picks = merge_and_select_daily_picks(candidates, max_picks=MAX_DAILY_PICKS)

        # 4. Enriquecer racha reciente (`team`) para los picks finales que aún no la tengan
        missing_form_ids = [
            tid
            for p in final_picks
            if not p.match.home_form or not p.match.away_form
            for tid in extract_team_ids_from_url(p.match.external_url)
        ]
        if missing_form_ids:
            extra_stats = _fetch_team_stats(missing_form_ids, tmp_dir / "teams_final.json")
            for p in final_picks:
                if p.match.home_form and p.match.away_form:
                    continue
                hs, as_ = _match_team_stats_to_sides(
                    p.match.home_team,
                    p.match.away_team,
                    p.match.external_url,
                    extra_stats,
                )
                if hs and hs.get("form"):
                    p.match.home_form = str(hs["form"])
                if as_ and as_.get("form"):
                    p.match.away_form = str(as_["form"])

    # 5. Enriquecimiento opcional con IA (solo si AI_API_KEY está presente)
    for p in final_picks:
        if p.short_reason is None:
            p.short_reason = generate_short_reason(
                {
                    "liga": p.match.league,
                    "local": p.match.home_team,
                    "visitante": p.match.away_team,
                    "pronostico": p.pick_label_es,
                    "mercado": p.market_raw,
                    "cuota": p.odds,
                    "casa": p.bookmaker,
                    "consenso_pct": p.consensus_pct,
                    "racha_local": p.match.home_form,
                    "racha_visitante": p.match.away_form,
                }
            )

    return final_picks, matches_evaluated


def main() -> int:
    parser = argparse.ArgumentParser(description="Recolección matutina de Monitor Deportivo")
    parser.add_argument("--dry-run", action="store_true", help="Ejecuta sin escribir en Supabase")
    parser.add_argument("--horizon-hours", type=int, default=48, help="Ventana futura de partidos en horas")
    args = parser.parse_args()

    repo: MonitorRepository | None = None
    run_id: int | None = None
    active_tipsters: list[dict[str, Any]] = []

    if not args.dry_run:
        repo = MonitorRepository(get_supabase_admin_client())
        run_id = repo.start_job_run("morning_fetch")
        active_tipsters = repo.get_active_tipsters()

    try:
        picks, matches_evaluated = collect_and_curate(
            active_tipsters=active_tipsters,
            horizon_hours=args.horizon_hours,
        )

        logger.info("Pronósticos seleccionados: %d (eventos evaluados: %d)", len(picks), matches_evaluated)
        for idx, p in enumerate(picks, start=1):
            logger.info(
                "  #%d [%s] %s vs %s -> %s @ %.2f (%s | consenso=%s%% | rank=%d)",
                idx,
                p.match.league,
                p.match.home_team,
                p.match.away_team,
                p.pick_label_es,
                p.odds,
                p.bookmaker,
                p.consensus_pct,
                p.confidence_rank,
            )

        local_today = datetime.now(ZoneInfo(USER_TIMEZONE)).date()

        if args.dry_run:
            parlay_preview = build_daily_parlay(
                [
                    ParlayLegCandidate(
                        prediction_id=i,
                        match_id=p.match.id,
                        odds=p.odds,
                        confidence_rank=p.confidence_rank,
                        consensus_pct=p.consensus_pct,
                        pick_label_es=p.pick_label_es,
                    )
                    for i, p in enumerate(picks, start=1)
                ],
                parlay_date=local_today,
            )
            if parlay_preview:
                logger.info(
                    "Parlay sugerido (dry-run): %s | Cuota total: %.2f | Patas: %s",
                    parlay_preview.title,
                    parlay_preview.total_odds,
                    [l.pick_label_es for l in parlay_preview.legs],
                )
            return 0

        assert repo is not None and run_id is not None
        match_rows = [p.match.to_db_row() for p in picks]
        pred_rows = [p.to_db_row() for p in picks]
        repo.upsert_matches(match_rows)
        saved_preds = repo.upsert_predictions(pred_rows)

        # Generar y guardar la Combinada (Parlay) sugerida del día
        parlay_candidates = [
            ParlayLegCandidate(
                prediction_id=int(row["id"]),
                match_id=str(row["match_id"]),
                odds=float(row["odds"]),
                confidence_rank=int(row["confidence_rank"]),
                consensus_pct=row.get("consensus_pct"),
                pick_label_es=str(row["pick_label_es"]),
            )
            for row in saved_preds
        ]
        parlay_plan = build_daily_parlay(parlay_candidates, parlay_date=local_today)
        if parlay_plan:
            parlay_id = repo.upsert_daily_parlay(
                parlay_plan.to_db_row(),
                [{"prediction_id": leg.prediction_id, "leg_odds": leg.odds} for leg in parlay_plan.legs],
            )
            logger.info(
                "Parlay diario guardado (#%d): %s @ %.2f (%d patas)",
                parlay_id,
                parlay_plan.title,
                parlay_plan.total_odds,
                len(parlay_plan.legs),
            )
        else:
            logger.info("No se generó parlay diario hoy (<2 partidos distintos en rango conservador 1.30–1.70).")

        status = "success" if len(saved_preds) >= MIN_DAILY_PICKS else ("partial" if saved_preds else "failed")
        repo.finish_job_run(
            run_id,
            status=status,
            matches_processed=matches_evaluated,
            predictions_saved=len(saved_preds),
        )
        return 0

    except Exception as exc:
        logger.exception("Error en morning_fetch: %s", exc)
        if repo is not None and run_id is not None:
            repo.finish_job_run(
                run_id,
                status="failed",
                matches_processed=0,
                predictions_saved=0,
                error_message=str(exc)[:1000],
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
