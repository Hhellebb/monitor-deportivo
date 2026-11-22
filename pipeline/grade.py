"""Motor de calificación automática (Grading) de pronósticos deportivos.

Implementa las reglas de negocio y casos borde críticos (Sección 5.3 del Plan):
- Fútbol estándar (1X2, BTTS, O/U, Double Chance, Moneyline sin DNB): evalúa
  estrictamente el tiempo reglamentario (90' + añadido), usando `partial_results`
  cuando el partido se definió en tiempo extra o penales.
- Draw No Bet (Empate No Válido): empate -> `void`.
- Baloncesto / Béisbol / Fútbol Americano: incluye tiempo extra / entradas extra.
- Partidos pospuestos o cancelados -> `void` inmediato.
- Líneas enteras de Over/Under (ej. Over 2.0 con marcador total = 2) -> `void`.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

GradeResult = Literal["won", "lost", "void", "pending"]

_OVERTIME_SPORTS = {"basketball", "baseball", "american-football"}
_VOID_STATUSES = {"postponed", "cancelled", "canceled", "abandoned", "awarded", "walkover"}


@dataclass(frozen=True)
class MatchOutcome:
    sport: str
    status: str  # 'finished', 'postponed', 'cancelled', 'pending', 'live'
    home_score: int | None
    away_score: int | None
    partial_results: str | None = None  # Ej. '(2:0, 2:0)' o '(0:1, 1:0, 0:0, 4:3)'


def extract_football_regulation_score(
    home_score: int,
    away_score: int,
    partial_results: str | None,
) -> tuple[int, int]:
    """Obtiene el marcador de los 90 minutos reglamentarios en fútbol.

    En OddsPortal:
    - Partido normal: partial_results = '(1:0, 1:1)' (1er tiempo, 2do tiempo) -> 2-1.
    - Partido con prórroga o penales: tiene 3 o 4 pares, ej. '(0:1, 1:0, 0:0, 4:3)'
      y el marcador global suma el gol ganador de penales. Sumando únicamente los
      dos primeros parciales obtenemos el marcador exacto al minuto 90.
    """
    if not partial_results:
        return home_score, away_score

    pairs = re.findall(r"(\d+)\s*:\s*(\d+)", partial_results)
    if len(pairs) >= 3:
        reg_home = int(pairs[0][0]) + int(pairs[1][0])
        reg_away = int(pairs[0][1]) + int(pairs[1][1])
        return reg_home, reg_away

    return home_score, away_score


def grade_prediction(
    market_raw: str,
    pick_raw: str,
    outcome: MatchOutcome,
) -> GradeResult:
    """Califica un pronóstico contra el resultado oficial del partido."""
    status = (outcome.status or "").strip().lower()

    # Caso borde 1: Partido pospuesto o cancelado -> void inmediato
    if status in _VOID_STATUSES:
        return "void"

    if status != "finished":
        return "pending"

    if outcome.home_score is None or outcome.away_score is None:
        return "pending"

    sport = (outcome.sport or "football").strip().lower()
    if sport == "soccer":
        sport = "football"

    # Seleccionar marcador aplicable: 90' en fútbol, marcador final con OT en NBA/MLB/NFL
    if sport == "football":
        h, a = extract_football_regulation_score(
            outcome.home_score,
            outcome.away_score,
            outcome.partial_results,
        )
    else:
        h, a = outcome.home_score, outcome.away_score

    m_low = market_raw.strip().lower()
    p_low = pick_raw.strip().lower()

    # 1. 1X2
    if m_low == "1x2":
        if p_low in ("home", "1"):
            return "won" if h > a else "lost"
        if p_low in ("draw", "x"):
            return "won" if h == a else "lost"
        if p_low in ("away", "2"):
            return "won" if a > h else "lost"
        return "void"

    # 2. Moneyline / Winner / Home-Away
    if m_low in ("moneyline", "winner", "home/away"):
        if sport in _OVERTIME_SPORTS:
            # En NBA/MLB/NFL los empates no ocurren normalmente, pero si pasara (ej. NFL tie) -> void
            if h == a:
                return "void"
            if p_low in ("home", "1"):
                return "won" if h > a else "lost"
            if p_low in ("away", "2"):
                return "won" if a > h else "lost"
            return "void"

        # Caso borde crítico (Sección 5.3): en fútbol estándar, Moneyline sin DNB evalúa 90'
        # y declara lost si hubo empate reglamentario.
        if p_low in ("home", "1"):
            return "won" if h > a else "lost"
        if p_low in ("away", "2"):
            return "won" if a > h else "lost"
        return "void"

    # 3. Draw No Bet (Empate No Válido)
    if m_low in ("draw no bet", "dnb"):
        if h == a:
            return "void"
        if p_low in ("home", "1"):
            return "won" if h > a else "lost"
        if p_low in ("away", "2"):
            return "won" if a > h else "lost"
        return "void"

    # 4. Double Chance
    if m_low == "double chance":
        if p_low == "1x":
            return "won" if h >= a else "lost"
        if p_low in ("x2", "2x"):
            return "won" if a >= h else "lost"
        if p_low == "12":
            return "won" if h != a else "lost"
        return "void"

    # 5. BTTS (Both Teams To Score)
    if m_low == "btts":
        both_scored = h > 0 and a > 0
        if p_low == "yes":
            return "won" if both_scored else "lost"
        if p_low == "no":
            return "won" if not both_scored else "lost"
        return "void"

    # 6. Over / Under X.X
    if m_low.startswith("over/under"):
        line_match = re.search(r"(\d+(?:\.\d+)?)", p_low) or re.search(r"(\d+(?:\.\d+)?)", m_low)
        if not line_match:
            return "void"
        line = float(line_match.group(1))
        total = float(h + a)

        if total == line:
            return "void"  # Push en líneas enteras (ej. Over 2.0 con 2 goles)

        if p_low.startswith("over"):
            return "won" if total > line else "lost"
        if p_low.startswith("under"):
            return "won" if total < line else "lost"
        return "void"

    return "void"


def calculate_tipster_stats(results: list[str]) -> tuple[int, int, float]:
    """Calcula (tracked_picks, won_picks, win_rate) ignorando picks 'pending' y 'void'."""
    decided = [r for r in results if r in ("won", "lost")]
    tracked = len(decided)
    won = sum(1 for r in decided if r == "won")
    win_rate = round((won / tracked) * 100.0, 2) if tracked > 0 else 0.0
    return tracked, won, win_rate
