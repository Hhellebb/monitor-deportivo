"""Generador y calificador automático de la Combinada (Parlay) sugerida del día."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import prod
from typing import Literal

from pipeline.config import (
    PARLAY_MAX_LEGS,
    PARLAY_MIN_LEGS,
    PARLAY_ODDS_MAX,
    PARLAY_ODDS_MIN,
)

ParlayResult = Literal["pending", "won", "lost", "void"]


@dataclass(frozen=True)
class ParlayLegCandidate:
    prediction_id: int
    match_id: str
    odds: float
    confidence_rank: int
    consensus_pct: int | None
    pick_label_es: str


@dataclass(frozen=True)
class DailyParlayPlan:
    parlay_date: str  # YYYY-MM-DD
    title: str
    total_odds: float
    legs: tuple[ParlayLegCandidate, ...]

    def to_db_row(self) -> dict[str, object]:
        return {
            "parlay_date": self.parlay_date,
            "title": self.title,
            "total_odds": self.total_odds,
            "adjusted_odds": self.total_odds,
            "legs_count": len(self.legs),
            "result": "pending",
        }


def build_daily_parlay(
    candidates: list[ParlayLegCandidate],
    *,
    parlay_date: date,
    min_odds: float = PARLAY_ODDS_MIN,
    max_odds: float = PARLAY_ODDS_MAX,
    min_legs: int = PARLAY_MIN_LEGS,
    max_legs: int = PARLAY_MAX_LEGS,
) -> DailyParlayPlan | None:
    """Construye 1 parlay conservador con 2 o 3 selecciones de partidos distintos.

    Reglas:
    1. Prioriza selecciones en la ventana conservadora [1.30, 1.70] ordenadas por
       mayor confidence_rank y consensus_pct.
    2. Garantiza que todas las patas pertenezcan a partidos distintos (`match_id` único).
    3. Si hay 3 selecciones sólidas en [1.30, 1.70] usa 3; si hay 2 usa 2.
    4. Devuelve None si no se reúnen al menos `min_legs` partidos distintos en rango.
    """
    conservative = [c for c in candidates if min_odds <= c.odds <= max_odds]

    def _rank_key(c: ParlayLegCandidate) -> tuple[int, int, float]:
        return (-c.confidence_rank, -(c.consensus_pct or 0), c.odds)

    chosen: list[ParlayLegCandidate] = []
    used_matches: set[str] = set()

    for cand in sorted(conservative, key=_rank_key):
        if cand.match_id in used_matches:
            continue
        chosen.append(cand)
        used_matches.add(cand.match_id)
        if len(chosen) >= max_legs:
            break

    if len(chosen) < min_legs:
        return None

    total_odds = round(prod(c.odds for c in chosen), 2)
    title = f"Combinada sugerida ({len(chosen)} selecciones)"
    return DailyParlayPlan(
        parlay_date=parlay_date.isoformat(),
        title=title,
        total_odds=total_odds,
        legs=tuple(chosen),
    )


def grade_parlay(legs: list[tuple[str, float]]) -> tuple[ParlayResult, float | None]:
    """Califica un parlay a partir de sus patas [(result, leg_odds), ...].

    Reglas:
    - Si al menos 1 pata es `lost` -> el parlay completo es `lost` de inmediato.
    - Si alguna pata sigue `pending` (y ninguna ha perdido) -> `pending`.
    - Si todas las patas son `void` -> `void` con momio ajustado 1.00.
    - Si todas las patas no anuladas son `won` -> `won`, recalculando `adjusted_odds`
      multiplicando solo las patas ganadas (excluyendo las `void`).
    """
    if not legs:
        return "void", 1.0

    results = [r.strip().lower() for r, _ in legs]

    if any(r == "lost" for r in results):
        orig = round(prod(o for _, o in legs), 2)
        return "lost", orig

    if any(r == "pending" for r in results):
        return "pending", None

    won_odds = [o for r, o in legs if r.strip().lower() == "won"]
    if not won_odds:
        return "void", 1.0

    adjusted = round(prod(won_odds), 2)
    return "won", adjusted
