"""Flujo matutino de recolección, curación y persistencia en Supabase.

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

from dotenv import load_dotenv

from pipeline.config import MAX_DAILY_PICKS, MIN_DAILY_PICKS, TARGET_LEAGUES
from pipeline.curate import (
    CuratedPrediction,
    curate_community_top_records,
    curate_match_vote_record,
    curate_tipster_profile,
    merge_and_select_daily_picks,
)
from pipeline.db import MonitorRepository, get_supabase_admin_client
from pipeline.utils import extract_event_id, normalize_match_url, parse_kickoff_utc

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("fetch_morning")


def _oddsharvester_exe() -> str:
    """Resuelve el ejecutable `oddsharvester` del mismo entorno Python activo."""
    bin_dir = Path(sys.executable).parent
    for candidate in ("oddsharvester.exe", "oddsharvester"):
        p = bin_dir / candidate
        if p.exists():
            return str(p)
    return "oddsharvester"


def _run_oddsharvester(args: list[str], output_file: Path) -> list[dict[str, Any]]:
    """Ejecuta OddsHarvester CLI en modo headless y devuelve la lista JSON resultante."""
    base_url = os.environ.get("OH_BASE_URL", "").strip()
    cmd = [_oddsharvester_exe(), *args, "--timezone", "UTC", "-f", "json", "-o", str(output_file), "--headless"]
    if base_url:
        cmd.extend(["--base-url", base_url])

    logger.info("Ejecutando: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        logger.warning("OddsHarvester terminó con código %s: %s", proc.returncode, proc.stderr[-500:])
    if not output_file.exists():
        return []
    try:
        data = json.loads(output_file.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        logger.error("JSON inválido en %s", output_file)
        return []


def _extract_best_odds_from_match(match_record: dict[str, Any], sport: str) -> dict[str, float]:
    """Extrae la mejor cuota disponible por outcome ('1', 'X', '2') del mercado principal."""
    market_key = "1x2_market" if sport == "football" else "home_away_market"
    rows = match_record.get(market_key) or match_record.get("moneyline_market") or []
    best: dict[str, float] = {}
    for row in rows:
        blocked = set(row.get("blocked_outcomes") or [])
        for outcome_key in ("1", "X", "2"):
            if outcome_key in blocked or outcome_key not in row:
                continue
            try:
                val = float(row[outcome_key])
            except (TypeError, ValueError):
                continue
            if val > best.get(outcome_key, 0.0):
                best[outcome_key] = val
    return best


def collect_and_curate(
    *,
    active_tipsters: list[dict[str, Any]],
    horizon_hours: int = 36,
) -> tuple[list[CuratedPrediction], int]:
    """Ejecuta estrategia híbrida:
    1. Top picks comunitarios por deporte (`community --sport`).
    2. Perfiles de tipsters activos (`community --user`).
    3. Complemento por ligas objetivo (`upcoming --links-only` + `community --match-url`)
       si aún no alcanzamos el mínimo de 5 picks diarios.
    """
    candidates: list[CuratedPrediction] = []
    matches_evaluated = 0
    now_utc = datetime.now(UTC)
    max_start_utc = now_utc + timedelta(hours=horizon_hours)

    with tempfile.TemporaryDirectory(prefix="oh_morning_") as tmp:
        tmp_dir = Path(tmp)

        # 1. Top picks comunitarios por cada deporte activo
        sports = list(dict.fromkeys(lg.sport for lg in TARGET_LEAGUES))
        for sport in sports:
            out = tmp_dir / f"community_{sport}.json"
            records = _run_oddsharvester(["community", "-s", sport], out)
            matches_evaluated += len(records)
            curated = curate_community_top_records(records, strict_league_filter=True)
            # Filtrar a ventana próxima (hoy/mañana)
            for p in curated:
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

        # 3. Si aún tenemos menos del mínimo (5 picks), inspeccionar partidos próximos de ligas objetivo
        prelim = merge_and_select_daily_picks(candidates, max_picks=MAX_DAILY_PICKS)
        if len(prelim) < MIN_DAILY_PICKS:
            seen_ids = {p.match.id for p in prelim}
            for league in TARGET_LEAGUES:
                if len(merge_and_select_daily_picks(candidates, max_picks=MAX_DAILY_PICKS)) >= MAX_DAILY_PICKS:
                    break
                links_out = tmp_dir / f"upcoming_{league.league_slug}.json"
                link_rows = _run_oddsharvester(
                    ["upcoming", "-s", league.sport, "-l", league.league_slug, "--links-only"],
                    links_out,
                )
                # Tomar hasta 4 partidos próximos por liga para no sobrecargar peticiones
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
                    if len(selected_links) >= 4:
                        break

                if not selected_links:
                    continue

                # Extraer cuotas principales y votos de la comunidad para esos partidos
                main_market = "1x2" if league.sport == "football" else "home_away"
                odds_out = tmp_dir / f"odds_{league.league_slug}.json"
                odds_args = ["upcoming", "-s", league.sport, "-m", main_market, "--preview-only"]
                for link in selected_links:
                    odds_args.extend(["--match-link", link])
                match_records = _run_oddsharvester(odds_args, odds_out)
                matches_evaluated += len(match_records)

                odds_by_event: dict[str, dict[str, float]] = {}
                for mrec in match_records:
                    eid = extract_event_id(str(mrec.get("match_link") or ""))
                    odds_by_event[eid] = _extract_best_odds_from_match(mrec, league.sport)

                for link in selected_links:
                    eid = extract_event_id(link)
                    odds_map = odds_by_event.get(eid)
                    if not odds_map:
                        continue
                    vote_out = tmp_dir / f"votes_{eid}.json"
                    vote_records = _run_oddsharvester(["community", "--match-url", link], vote_out)
                    if not vote_records:
                        continue
                    pick = curate_match_vote_record(
                        vote_records[0],
                        league_name=league.league_name,
                        sport=league.sport,
                        odds_by_outcome=odds_map,
                    )
                    if pick is not None:
                        candidates.append(pick)

    final_picks = merge_and_select_daily_picks(candidates, max_picks=MAX_DAILY_PICKS)
    return final_picks, matches_evaluated


def main() -> int:
    parser = argparse.ArgumentParser(description="Recolección matutina de Monitor Deportivo")
    parser.add_argument("--dry-run", action="store_true", help="Ejecuta sin escribir en Supabase")
    parser.add_argument("--horizon-hours", type=int, default=36, help="Ventana futura de partidos en horas")
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

        logger.info("Pronósticos seleccionados para hoy: %d (eventos evaluados: %d)", len(picks), matches_evaluated)
        for idx, p in enumerate(picks, start=1):
            logger.info(
                "  #%d [%s] %s vs %s -> %s @ %.2f (consenso=%s%%, rank=%d, inicio=%s)",
                idx,
                p.match.league,
                p.match.home_team,
                p.match.away_team,
                p.pick_label_es,
                p.odds,
                p.consensus_pct,
                p.confidence_rank,
                p.match.start_time,
            )

        if args.dry_run:
            return 0

        assert repo is not None and run_id is not None
        match_rows = [p.match.to_db_row() for p in picks]
        pred_rows = [p.to_db_row() for p in picks]
        repo.upsert_matches(match_rows)
        saved = repo.upsert_predictions(pred_rows)

        status = "success" if saved > 0 else "partial"
        repo.finish_job_run(
            run_id,
            status=status,
            matches_processed=matches_evaluated,
            predictions_saved=saved,
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
