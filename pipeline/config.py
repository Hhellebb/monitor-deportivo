"""Configuración central del pipeline Monitor Deportivo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class LeagueConfig:
    sport: str  # Slug CLI de OddsHarvester: 'football', 'basketball', etc.
    sport_label_es: str  # Etiqueta visible en la PWA
    league_slug: str  # Slug CLI de OddsHarvester
    league_name: str  # Nombre limpio para UI y BD
    default_markets: tuple[str, ...]
    includes_overtime: bool  # True en NBA/MLB/NFL; False en 90' de fútbol


# Ligas activas iniciales para Etapa A (Validación) y Etapa B
TARGET_LEAGUES: Final[tuple[LeagueConfig, ...]] = (
    LeagueConfig(
        sport="football",
        sport_label_es="Fútbol",
        league_slug="mexico-liga-mx",
        league_name="Liga MX",
        default_markets=("1x2", "over_under_2_5", "btts"),
        includes_overtime=False,
    ),
    LeagueConfig(
        sport="football",
        sport_label_es="Fútbol",
        league_slug="england-premier-league",
        league_name="Premier League",
        default_markets=("1x2", "over_under_2_5", "btts"),
        includes_overtime=False,
    ),
    LeagueConfig(
        sport="football",
        sport_label_es="Fútbol",
        league_slug="spain-laliga",
        league_name="LaLiga",
        default_markets=("1x2", "over_under_2_5", "btts"),
        includes_overtime=False,
    ),
    LeagueConfig(
        sport="basketball",
        sport_label_es="NBA",
        league_slug="nba",
        league_name="NBA",
        default_markets=("home_away",),
        includes_overtime=True,
    ),
)

# Reglas de selección diaria (Sección 5 del Plan)
MIN_COMMUNITY_CONSENSUS_PCT: Final[int] = 70
MIN_TIPSTER_WIN_RATE_PCT: Final[float] = 58.0
MIN_DAILY_PICKS: Final[int] = 5
MAX_DAILY_PICKS: Final[int] = 8
IDEAL_ODDS_MIN: Final[float] = 1.40
IDEAL_ODDS_MAX: Final[float] = 2.25

# Zona horaria del usuario (todas las fechas en BD se guardan estrictamente en UTC)
USER_TIMEZONE: Final[str] = "America/Mazatlan"
