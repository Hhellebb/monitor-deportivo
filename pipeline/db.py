"""Capa de persistencia en Supabase (PostgreSQL) usando service_role_key."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


def get_supabase_admin_client() -> Client:
    """Inicializa cliente administrativo de Supabase para escrituras del backend."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError(
            "Faltan variables de entorno SUPABASE_URL y/o SUPABASE_SERVICE_ROLE_KEY."
        )
    return create_client(url, key)


class MonitorRepository:
    """Operaciones de lectura/escritura sobre matches, predictions, parlays, tipsters y job_runs."""

    def __init__(self, client: Client) -> None:
        self.client = client

    # --- job_runs ---
    def start_job_run(self, job_name: str) -> int:
        res = (
            self.client.table("job_runs")
            .insert({"job_name": job_name, "status": "running"})
            .execute()
        )
        return int(res.data[0]["id"])

    def finish_job_run(
        self,
        run_id: int,
        *,
        status: str,
        matches_processed: int,
        predictions_saved: int,
        error_message: str | None = None,
    ) -> None:
        (
            self.client.table("job_runs")
            .update(
                {
                    "finished_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "status": status,
                    "matches_processed": matches_processed,
                    "predictions_saved": predictions_saved,
                    "error_message": error_message,
                }
            )
            .eq("id", run_id)
            .execute()
        )

    # --- matches & predictions ---
    def upsert_matches(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        by_id = {r["id"]: r for r in rows}
        self.client.table("matches").upsert(list(by_id.values()), on_conflict="id").execute()
        return len(by_id)

    def upsert_predictions(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []
        res = (
            self.client.table("predictions")
            .upsert(rows, on_conflict="match_id,market_raw,pick_raw")
            .execute()
        )
        return list(res.data or [])

    # --- parlays & parlay_legs ---
    def upsert_daily_parlay(
        self,
        parlay_row: dict[str, Any],
        legs: list[dict[str, Any]],
    ) -> int:
        res = (
            self.client.table("parlays")
            .upsert(parlay_row, on_conflict="parlay_date")
            .execute()
        )
        parlay_id = int(res.data[0]["id"])

        # Reemplazar patas del parlay del día de forma idempotente
        self.client.table("parlay_legs").delete().eq("parlay_id", parlay_id).execute()
        leg_rows = [
            {
                "parlay_id": parlay_id,
                "prediction_id": int(leg["prediction_id"]),
                "leg_odds": round(float(leg["leg_odds"]), 2),
                "leg_order": idx,
            }
            for idx, leg in enumerate(legs, start=1)
        ]
        if leg_rows:
            self.client.table("parlay_legs").insert(leg_rows).execute()
        return parlay_id

    def get_pending_parlays_with_legs(self) -> list[dict[str, Any]]:
        res = (
            self.client.table("parlays")
            .select("*, parlay_legs(id, leg_odds, leg_order, predictions(id, result))")
            .eq("result", "pending")
            .execute()
        )
        return list(res.data or [])

    def update_parlay_result(
        self,
        parlay_id: int,
        *,
        result: str,
        adjusted_odds: float | None,
    ) -> None:
        (
            self.client.table("parlays")
            .update(
                {
                    "result": result,
                    "adjusted_odds": adjusted_odds,
                    "graded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
            .eq("id", parlay_id)
            .execute()
        )

    # --- tipsters & grading ---
    def get_active_tipsters(self) -> list[dict[str, Any]]:
        res = self.client.table("tipsters").select("*").eq("active", True).execute()
        return list(res.data or [])

    def get_pending_matches_for_grading(self, min_hours_after_kickoff: float = 2.0) -> list[dict[str, Any]]:
        cutoff = (datetime.now(UTC) - timedelta(hours=min_hours_after_kickoff)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        res = (
            self.client.table("matches")
            .select("*, predictions(*)")
            .in_("status", ["pending", "live"])
            .lte("start_time", cutoff)
            .execute()
        )
        return list(res.data or [])

    def update_match_outcome(
        self,
        match_id: str,
        *,
        status: str,
        home_score: int | None,
        away_score: int | None,
        partial_results: str | None = None,
    ) -> None:
        final_score = (
            f"{home_score} - {away_score}"
            if home_score is not None and away_score is not None
            else None
        )
        (
            self.client.table("matches")
            .update(
                {
                    "status": status,
                    "home_score": home_score,
                    "away_score": away_score,
                    "final_score": final_score,
                    "partial_results": partial_results,
                }
            )
            .eq("id", match_id)
            .execute()
        )

    def update_prediction_result(self, prediction_id: int, result: str) -> None:
        (
            self.client.table("predictions")
            .update(
                {
                    "result": result,
                    "graded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
            .eq("id", prediction_id)
            .execute()
        )

    def get_tipster_prediction_results(self, username: str) -> list[str]:
        res = (
            self.client.table("predictions")
            .select("result")
            .eq("source_type", "tipster")
            .eq("source_name", username)
            .execute()
        )
        return [str(r["result"]) for r in (res.data or [])]

    def update_tipster_stats(
        self,
        username: str,
        *,
        tracked_picks: int,
        won_picks: int,
        win_rate: float,
    ) -> None:
        (
            self.client.table("tipsters")
            .update(
                {
                    "tracked_picks": tracked_picks,
                    "won_picks": won_picks,
                    "win_rate": win_rate,
                }
            )
            .eq("username", username)
            .execute()
        )
