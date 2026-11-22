"""Configuración central del pipeline Monitor Deportivo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class LeagueConfig:
    sport: str  # Slug CLI de OddsHarvester: 'football', 'basketball', 'american-football'
    sport_label_es: str  # Etiqueta visible en la PWA
    league_slug: str  # Slug CLI de OddsHarvester
    league_name: str  # Nombre limpio para UI y BD
    default_markets: tuple[str, ...]
    includes_overtime: bool  # True en NBA/NFL; False en 90' de fútbol


# 5 Ligas iniciales solicitadas: NBA, NFL, Bundesliga, LaLiga y Liga MX
TARGET_LEAGUES: Final[tuple[LeagueConfig, ...]] = (
    LeagueConfig(
        sport="football",
        sport_label_es="Fútbol",
        league_slug="mexico-liga-mx",
        league_name="Liga MX",
        default_markets=("1x2", "over_under_2_5", "btts", "double_chance"),
        includes_overtime=False,
    ),
    LeagueConfig(
        sport="football",
        sport_label_es="Fútbol",
        league_slug="spain-laliga",
        league_name="LaLiga",
        default_markets=("1x2", "over_under_2_5", "btts", "double_chance"),
        includes_overtime=False,
    ),
    LeagueConfig(
        sport="football",
        sport_label_es="Fútbol",
        league_slug="germany-bundesliga",
        league_name="Bundesliga",
        default_markets=("1x2", "over_under_2_5", "btts", "double_chance"),
        includes_overtime=False,
    ),
    LeagueConfig(
        sport="basketball",
        sport_label_es="NBA",
        league_slug="nba",
        league_name="NBA",
        default_markets=("home_away", "over_under"),
        includes_overtime=True,
    ),
    LeagueConfig(
        sport="american-football",
        sport_label_es="NFL",
        league_slug="nfl",
        league_name="NFL",
        default_markets=("home_away", "over_under"),
        includes_overtime=True,
    ),
)

# Casa de apuestas de referencia principal (con fallback automático si no está listada)
REFERENCE_BOOKMAKER: Final[str] = "bet365"

# Reglas de selección diaria individual
MIN_COMMUNITY_CONSENSUS_PCT: Final[int] = 70
MIN_TIPSTER_WIN_RATE_PCT: Final[float] = 58.0
MIN_DAILY_PICKS: Final[int] = 5
MAX_DAILY_PICKS: Final[int] = 8
IDEAL_ODDS_MIN: Final[float] = 1.40
IDEAL_ODDS_MAX: Final[float] = 2.25

# Reglas de Combinada (Parlay) sugerida del día
PARLAY_MIN_LEGS: Final[int] = 2
PARLAY_MAX_LEGS: Final[int] = 3
PARLAY_ODDS_MIN: Final[float] = 1.30
PARLAY_ODDS_MAX: Final[float] = 1.70

# Zona horaria del usuario (todas las fechas en BD se guardan estrictamente en UTC)
USER_TIMEZONE: Final[str] = "America/Mazatlan"
