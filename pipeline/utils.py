"""Utilidades de normalización de URLs, IDs y fechas UTC para OddsHarvester."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import re
from urllib.parse import urlparse

CANONICAL_HOST = "https://www.oddsportal.com"

_SPANISH_MONTHS: dict[str, int] = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}

_ENGLISH_MONTHS: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def extract_event_id(match_url: str) -> str:
    """Extrae el event_id estable desde el fragmento (#CSnuq6U8 o #CSnuq6U8:1X2;2).

    Si la URL no incluye fragmento válido, genera un hash estable corto de la ruta.
    """
    parsed = urlparse(match_url.strip())
    if parsed.fragment:
        token = parsed.fragment.split(":", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{6,16}", token):
            return token
    canonical_path = parsed.path.rstrip("/")
    return hashlib.sha1(canonical_path.encode("utf-8")).hexdigest()[:12]


def normalize_match_url(match_url: str) -> str:
    """Convierte cualquier espejo regional (ej. cuotasahora.com) a URL canónica de OddsPortal
    sin sufijos de mercado (:1X2;2).
    """
    parsed = urlparse(match_url.strip())
    path = parsed.path
    if not path.endswith("/"):
        path = f"{path}/"
    event_id = extract_event_id(match_url)
    if parsed.fragment:
        return f"{CANONICAL_HOST}{path}#{event_id}"
    return f"{CANONICAL_HOST}{path}"


def parse_kickoff_utc(
    kickoff: str | None = None,
    kickoff_text: str | None = None,
    match_date: str | None = None,
    scraped_at: str | None = None,
) -> datetime | None:
    """Convierte las variantes de fecha/hora que emite OddsHarvester en datetime UTC.

    Soporta:
    - match_date: '2026-11-23 20:00:00 UTC'
    - kickoff ISO: '2026-11-26T17:45' (asumido en UTC porque se ejecuta con --timezone UTC)
    - kickoff largo: 'Monday, 23 Nov 2026, 20:00'
    - kickoff_text en inglés/español: 'Today 23:00', 'Tomorrow 20:00', 'Hoy 23:00', 'Mañana 20:00',
      '26/nov. 17:45', '26 Nov 17:45'
    """
    ref_utc = _parse_reference_utc(scraped_at)

    # 1. match_date explícito en UTC (upcoming / historic)
    if match_date:
        clean = match_date.strip().removesuffix(" UTC").strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(clean, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue

    # 2. kickoff ISO o encabezado legible
    if kickoff:
        raw = kickoff.strip()
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass

        for fmt in ("%A, %d %b %Y, %H:%M", "%d %b %Y, %H:%M", "%d %b %Y %H:%M"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue

    # 3. Fallback kickoff_text (especialmente espejo cuotasahora.com: 'Hoy 23:00', 'Mañana 20:00')
    if kickoff_text:
        text = kickoff_text.strip()

        # Relativos Hoy / Today / Mañana / Tomorrow / Ayer / Yesterday
        rel_match = re.search(
            r"\b(hoy|today|mañana|manana|tomorrow|ayer|yesterday)\b[,\s]+(\d{1,2}):(\d{2})",
            text,
            flags=re.IGNORECASE,
        )
        if rel_match:
            word = rel_match.group(1).lower()
            hour, minute = int(rel_match.group(2)), int(rel_match.group(3))
            day_offset = 0
            if word in ("mañana", "manana", "tomorrow"):
                day_offset = 1
            elif word in ("ayer", "yesterday"):
                day_offset = -1
            base_day = (ref_utc + timedelta(days=day_offset)).date()
            return datetime(base_day.year, base_day.month, base_day.day, hour, minute, tzinfo=UTC)

        # Fecha corta: '26/nov. 17:45' o '26 Nov 17:45'
        dm_match = re.search(
            r"\b(\d{1,2})[/\s]+([a-záéíóú]{3,4})\.?[,\s]+(\d{1,2}):(\d{2})",
            text,
            flags=re.IGNORECASE,
        )
        if dm_match:
            day = int(dm_match.group(1))
            mon_token = dm_match.group(2).lower()
            month = _SPANISH_MONTHS.get(mon_token) or _ENGLISH_MONTHS.get(mon_token)
            if month:
                hour, minute = int(dm_match.group(3)), int(dm_match.group(4))
                year = ref_utc.year
                candidate = datetime(year, month, day, hour, minute, tzinfo=UTC)
                # Manejo de cruce de año (ej. scraping en diciembre para partido de enero)
                if candidate < ref_utc - timedelta(days=180):
                    candidate = candidate.replace(year=year + 1)
                return candidate

    return None


def to_utc_iso(dt: datetime) -> str:
    """Formatea un datetime a cadena estricta UTC ISO-8601 (YYYY-MM-DDTHH:MM:SSZ)."""
    utc_dt = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_reference_utc(scraped_at: str | None) -> datetime:
    if scraped_at:
        try:
            dt = datetime.fromisoformat(scraped_at.strip().replace("Z", "+00:00"))
            return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)
