"""Flujo nocturno de calificación automática (Grading) de picks individuales y parlays.

Ejecución local (sin escribir en BD):
    python -m pipeline.grade_night --dry-run

Ejecución productiva (GitHub Actions):
    python -m pipeline.grade_night
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from dotenv import load_dotenv

from pipeline.db import MonitorRepository, get_supabase_admin_client
from pipeline.grade import MatchOutcome, calculate_tipster_stats, grade_prediction
from pipeline.parlay import grade_parlay
from pipeline.utils import extract_event_id, normalize_match_url

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("grade_night")


def _oddsharvester_exe() -> str:
    bin_dir = Path(sys.executable).parent
    for candidate in ("oddsharvester.exe", "oddsharvester"):
        p = bin_dir / candidate
        if p.exists():
            return str(p)
    return "oddsharvester"


def _fetch_historic_by_links(sport: str, links: list[str], out_file: Path) -> list[dict[str, Any]]:
    base_url = os.environ.get("OH_BASE_URL", "").strip()
    main_market = "1x2" if sport == "football" else "home_away"
    cmd = [
        _oddsharvester_exe(),
        "historic",
        "-s",
        sport,
        "-m",
        main_market,
        "--preview-only",
        "--timezone",
        "UTC",
        "-f",
        "json",
        "-o",
        str(out_file),
        "--headless",
    ]
    for link in links:
        cmd.extend(["--match-link", normalize_match_url(link)])
    if base_url:
        cmd.extend(["--base-url", base_url])

    logger.info("Consultando marcadores históricos (%s): %d partido(s)", sport, len(links))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        logger.warning("OddsHarvester historic terminó con código %s: %s", proc.returncode, proc.stderr[-400:])
    if not out_file.exists():
        return []
    try:
        data = json.loads(out_file.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _parse_outcome(record: dict[str, Any], sport: str) -> MatchOutcome:
    info = str(record.get("match_info") or "").lower()
    if any(k in info for k in ("postponed", "pospuesto", "aplazado")):
        return MatchOutcome(sport=sport, status="postponed", home_score=None, away_score=None)
    if any(k in info for k in ("cancelled", "canceled", "cancelado", "abandoned", "suspendido")):
        return MatchOutcome(sport=sport, status="cancelled", home_score=None, away_score=None)

    hs_raw = record.get("home_score")
    as_raw = record.get("away_score")
    if hs_raw is None or as_raw is None or str(hs_raw).strip() == "" or str(as_raw).strip() == "":
        return MatchOutcome(sport=sport, status="pending", home_score=None, away_score=None)

    try:
        hs = int(str(hs_raw).strip())
        aw = int(str(as_raw).strip())
    except ValueError:
        return MatchOutcome(sport=sport, status="pending", home_score=None, away_score=None)

    return MatchOutcome(
        sport=sport,
        status="finished",
        home_score=hs,
        away_score=aw,
        partial_results=record.get("partial_results"),
    )


def _grade_pending_parlays(repo: MonitorRepository, *, dry_run: bool) -> int:
    """Evalúa todos los parlays pendientes en Supabase tras calificar picks individuales."""
    pending_parlays = repo.get_pending_parlays_with_legs()
    graded_count = 0

    for parlay in pending_parlays:
        legs_raw = parlay.get("parlay_legs") or []
        leg_pairs: list[tuple[str, float]] = []
        for leg in legs_raw:
            pred = leg.get("predictions") or {}
            leg_pairs.append((str(pred.get("result") or "pending"), float(leg["leg_odds"])))

        verdict, adjusted_odds = grade_parlay(leg_pairs)
        if verdict == "pending":
            continue

        logger.info(
            "Parlay #%s (%s) => %s (cuota ajustada: %s)",
            parlay["id"],
            parlay["parlay_date"],
            verdict.upper(),
            adjusted_odds,
        )
        if not dry_run:
            repo.update_parlay_result(
                int(parlay["id"]),
                result=verdict,
                adjusted_odds=adjusted_odds,
            )
        graded_count += 1

    return graded_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Calificación nocturna automática de Monitor Deportivo")
    parser.add_argument("--dry-run", action="store_true", help="Solo imprime resultados sin escribir en Supabase")
    parser.add_argument("--min-hours", type=float, default=2.0, help="Horas mínimas desde kickoff para calificar")
    args = parser.parse_args()

    repo = MonitorRepository(get_supabase_admin_client())
    run_id: int | None = None if args.dry_run else repo.start_job_run("night_grade")

    try:
        pending_matches = repo.get_pending_matches_for_grading(min_hours_after_kickoff=args.min_hours)
        matches_updated = 0
        predictions_graded = 0
        touched_tipsters: set[str] = set()

        if pending_matches:
            by_sport: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for m in pending_matches:
                by_sport[str(m["sport"])].append(m)

            scraped_by_id: dict[str, dict[str, Any]] = {}
            with tempfile.TemporaryDirectory(prefix="oh_grade_") as tmp:
                tmp_dir = Path(tmp)
                for sport, matches in by_sport.items():
                    links = [str(m["external_url"]) for m in matches]
                    records = _fetch_historic_by_links(sport, links, tmp_dir / f"hist_{sport}.json")
                    for rec in records:
                        eid = extract_event_id(str(rec.get("match_link") or ""))
                        scraped_by_id[eid] = rec

            for m in pending_matches:
                match_id = str(m["id"])
                sport = str(m["sport"])
                rec = scraped_by_id.get(match_id)
                if not rec:
                    logger.warning("Sin resultado aún para partido %s (%s vs %s)", match_id, m["home_team"], m["away_team"])
                    continue

                outcome = _parse_outcome(rec, sport)
                if outcome.status == "pending":
                    logger.info("Partido %s aún sin marcador definitivo.", match_id)
                    continue

                logger.info(
                    "Partido %s (%s vs %s): status=%s marcador=%s-%s parciales=%s",
                    match_id,
                    m["home_team"],
                    m["away_team"],
                    outcome.status,
                    outcome.home_score,
                    outcome.away_score,
                    outcome.partial_results,
                )

                if not args.dry_run:
                    repo.update_match_outcome(
                        match_id,
                        status=outcome.status,
                        home_score=outcome.home_score,
                        away_score=outcome.away_score,
                        partial_results=outcome.partial_results,
                    )
                matches_updated += 1

                for pred in m.get("predictions") or []:
                    if pred.get("result") != "pending":
                        continue
                    verdict = grade_prediction(
                        market_raw=str(pred["market_raw"]),
                        pick_raw=str(pred["pick_raw"]),
                        outcome=outcome,
                    )
                    if verdict == "pending":
                        continue

                    logger.info(
                        "  -> Predicción #%s (%s) => %s",
                        pred["id"],
                        pred["pick_label_es"],
                        verdict.upper(),
                    )
                    if not args.dry_run:
                        repo.update_prediction_result(int(pred["id"]), verdict)
                    predictions_graded += 1

                    if pred.get("source_type") == "tipster":
                        touched_tipsters.add(str(pred["source_name"]))

        # Calificar parlays pendientes (ajusta momio automáticamente ante patas void)
        parlays_graded = _grade_pending_parlays(repo, dry_run=args.dry_run)
        if parlays_graded:
            logger.info("Parlays calificados: %d", parlays_graded)

        # Recalcular win_rate de tipsters afectados
        if not args.dry_run:
            for username in touched_tipsters:
                results = repo.get_tipster_prediction_results(username)
                tracked, won, win_rate = calculate_tipster_stats(results)
                repo.update_tipster_stats(
                    username,
                    tracked_picks=tracked,
                    won_picks=won,
                    win_rate=win_rate,
                )
                logger.info("Tipster %s actualizado: %d/%d (%.2f%%)", username, won, tracked, win_rate)

            if run_id is not None:
                status = (
                    "success"
                    if not pending_matches or matches_updated == len(pending_matches)
                    else "partial"
                )
                repo.finish_job_run(
                    run_id,
                    status=status,
                    matches_processed=matches_updated,
                    predictions_saved=predictions_graded,
                )

        return 0

    except Exception as exc:
        logger.exception("Error en grade_night: %s", exc)
        if run_id is not None:
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
