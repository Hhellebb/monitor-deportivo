"""Diccionario de normalización y traducción de mercados técnicos a español natural."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TranslatedPick:
    market_raw: str       # Mercado canónico para BD y grading (ej. '1X2', 'Over/Under 2.5', 'Moneyline')
    pick_raw: str         # Selección canónica (ej. 'Home', 'Draw', 'Away', 'Over 2.5', 'Yes', '1X')
    pick_label_es: str    # Texto amigable en español para la PWA (ej. 'Gana Club América')


_UNIT_BY_SPORT: dict[str, str] = {
    "football": "goles",
    "soccer": "goles",
    "basketball": "puntos",
    "american-football": "puntos",
    "baseball": "carreras",
    "ice-hockey": "goles",
}


def normalize_and_translate(
    market: str,
    outcome: str,
    home_team: str,
    away_team: str,
    sport: str = "football",
) -> TranslatedPick | None:
    """Normaliza un mercado/selección cruda de OddsPortal/CuotasAhora y devuelve
    su etiqueta clara en español según el diccionario del plan (Sección 5.2).

    Devuelve None si el mercado no es uno de los soportados por el producto
    (ej. marcador exacto 'CS' o handicaps asiáticos complejos de cuartos).
    """
    m = market.strip()
    m_low = m.lower()
    o = outcome.strip()
    o_low = o.lower()
    sport_low = sport.lower()
    unit = _UNIT_BY_SPORT.get(sport_low, "goles / puntos")

    # 1. 1X2 (Resultado en tiempo reglamentario)
    if m_low in ("1x2", "1x2, ft", "1x2 full time"):
        if o_low in ("1", "home", "home (1)", "local"):
            return TranslatedPick("1X2", "Home", f"Gana {home_team}")
        if o_low in ("x", "draw", "draw (x)", "empate"):
            return TranslatedPick("1X2", "Draw", "Empate")
        if o_low in ("2", "away", "away (2)", "visitante"):
            return TranslatedPick("1X2", "Away", f"Gana {away_team}")
        return None

    # 2. Moneyline / Home-Away / Winner (incl. 'H/A, prór.', 'Home/Away', 'ML')
    if any(
        token in m_low
        for token in ("moneyline", "winner", "home/away", "home-away", "h/a", "ml")
    ):
        includes_ot = sport_low in ("basketball", "baseball", "american-football") or any(
            k in m_low for k in ("prór", "pror", "ot", "extra")
        )
        suffix = " (Incluye T. Extra)" if includes_ot else ""
        if o_low in ("1", "home", "local"):
            return TranslatedPick("Moneyline", "Home", f"Gana {home_team}{suffix}")
        if o_low in ("2", "away", "visitante"):
            return TranslatedPick("Moneyline", "Away", f"Gana {away_team}{suffix}")
        return None

    # 3. Draw No Bet (Empate No Válido)
    if any(token in m_low for token in ("draw no bet", "dnb", "empate no", "sin empate")):
        if o_low in ("1", "home", "local"):
            return TranslatedPick("Draw No Bet", "Home", f"Gana {home_team} (Empate anula)")
        if o_low in ("2", "away", "visitante"):
            return TranslatedPick("Draw No Bet", "Away", f"Gana {away_team} (Empate anula)")
        return None

    # 4. Double Chance (Doble Oportunidad)
    if any(token in m_low for token in ("double chance", "doble oportunidad", "dc")):
        compact = o_low.replace(" ", "")
        if compact in ("1x", "homeordraw"):
            return TranslatedPick("Double Chance", "1X", f"{home_team} gana o empata")
        if compact in ("x2", "2x", "awayordraw", "draworaway"):
            return TranslatedPick("Double Chance", "X2", f"{away_team} gana o empata")
        if compact in ("12", "homeoraway"):
            return TranslatedPick("Double Chance", "12", "Gana cualquiera (sin empate)")
        return None

    # 5. BTTS (Ambos Equipos Anotan)
    if any(token in m_low for token in ("btts", "both teams to score", "ambos equipos", "bts")):
        if o_low in ("yes", "si", "sí", "btts_yes", "1"):
            return TranslatedPick("BTTS", "Yes", "Ambos equipos anotan")
        if o_low in ("no", "btts_no", "2"):
            return TranslatedPick("BTTS", "No", "No anotan ambos equipos")
        return None

    # 6. Over / Under (Más / Menos de X.X goles/puntos)
    if any(token in m_low for token in ("over/under", "over_under", "o/u", "más/menos", "mas/menos", "total")):
        line = _extract_line(m) or _extract_line(o)
        if line is None:
            return None
        is_over = any(k in o_low for k in ("over", "más", "mas", "+", "1")) and "under" not in o_low
        is_under = any(k in o_low for k in ("under", "menos", "-", "2")) and "over" not in o_low
        if is_over:
            return TranslatedPick(
                f"Over/Under {line}",
                f"Over {line}",
                f"Más de {line} {unit}",
            )
        if is_under:
            return TranslatedPick(
                f"Over/Under {line}",
                f"Under {line}",
                f"Menos de {line} {unit}",
            )
        return None

    return None


def _extract_line(text: str) -> str | None:
    """Extrae la línea numérica de Over/Under (ej. '2.5', '218.5', '3') normalizada."""
    cleaned = text.replace("_", ".").replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    if not match:
        return None
    val = float(match.group(1))
    # Evitar ceros sobrantes innecesarios (2.50 -> 2.5; 3.0 -> 3.0 o 3)
    if val.is_integer():
        return f"{val:.1f}"
    return f"{val:g}"
