-- =============================================================================
-- Monitor Deportivo — Esquema PostgreSQL + Políticas RLS (Supabase)
-- Todas las fechas se almacenan estrictamente en TIMESTAMPTZ (UTC).
-- =============================================================================

-- Extensiones necesarias (gen_random_uuid ya viene en pgcrypto / PG13+)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -----------------------------------------------------------------------------
-- 1. Tabla: matches
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.matches (
    id              TEXT PRIMARY KEY,              -- event_id estable de OddsPortal (ej. 'CSnuq6U8')
    external_url    TEXT NOT NULL,                 -- URL canónica en www.oddsportal.com
    sport           TEXT NOT NULL,                 -- 'football', 'basketball', 'baseball', 'american-football'
    league          TEXT NOT NULL,                 -- Nombre legible (ej. 'Liga MX', 'Premier League', 'NBA')
    home_team       TEXT NOT NULL,
    away_team       TEXT NOT NULL,
    start_time      TIMESTAMPTZ NOT NULL,          -- Siempre UTC ISO-8601
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'live', 'finished', 'postponed', 'cancelled')),
    final_score     TEXT,                          -- Ej. '2 - 1'
    home_score      INTEGER,
    away_score      INTEGER,
    partial_results TEXT,                          -- Parciales de OddsPortal (ej. '(2:0, 2:0)')
    home_form       TEXT,                          -- Racha últimos 5-6 partidos (opcional, ej. 'WWDLW')
    away_form       TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_matches_start_time ON public.matches (start_time DESC);
CREATE INDEX IF NOT EXISTS idx_matches_status ON public.matches (status);
CREATE INDEX IF NOT EXISTS idx_matches_sport_start ON public.matches (sport, start_time DESC);

-- -----------------------------------------------------------------------------
-- 2. Tabla: predictions
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.predictions (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id        TEXT NOT NULL REFERENCES public.matches(id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL
                    CHECK (source_type IN ('community', 'tipster', 'hybrid')),
    source_name     TEXT NOT NULL,                 -- Ej. 'Consenso Comunidad' o username de tipster
    market_raw      TEXT NOT NULL,                 -- Mercado normalizado: '1X2', 'Over/Under 2.5', 'BTTS', 'Moneyline', etc.
    pick_raw        TEXT NOT NULL,                 -- Selección normalizada: 'Home', 'Draw', 'Away', 'Over 2.5', 'Yes', '1X', etc.
    pick_label_es   TEXT NOT NULL,                 -- Texto claro en español para la UI (ej. 'Gana Club América')
    odds            NUMERIC(6, 2) NOT NULL CHECK (odds > 1.00),
    bookmaker       TEXT NOT NULL DEFAULT 'bet365',-- Casa de apuestas de referencia (bet365 o fallback)
    consensus_pct   INTEGER CHECK (consensus_pct IS NULL OR (consensus_pct BETWEEN 0 AND 100)),
    vote_breakdown  JSONB,                         -- Desglose exacto de votos para 'Ver detalle' (ej. [{"outcome":"1","pct":82},...])
    short_reason    TEXT,                          -- Reservado para justificación breve (IA futura o nota estadística)
    confidence_rank INTEGER NOT NULL CHECK (confidence_rank BETWEEN 1 AND 10),
    result          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (result IN ('pending', 'won', 'lost', 'void')),
    graded_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_predictions_match_market_pick UNIQUE (match_id, market_raw, pick_raw)
);

CREATE INDEX IF NOT EXISTS idx_predictions_match_id ON public.predictions (match_id);
CREATE INDEX IF NOT EXISTS idx_predictions_result ON public.predictions (result);
CREATE INDEX IF NOT EXISTS idx_predictions_graded_at ON public.predictions (graded_at DESC);

-- -----------------------------------------------------------------------------
-- 3. Tabla: tipsters
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.tipsters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        TEXT NOT NULL UNIQUE,
    sport_focus     TEXT NOT NULL,                 -- Ej. 'football', 'basketball', 'all'
    tracked_picks   INTEGER NOT NULL DEFAULT 0 CHECK (tracked_picks >= 0),
    won_picks       INTEGER NOT NULL DEFAULT 0 CHECK (won_picks >= 0),
    win_rate        NUMERIC(5, 2) NOT NULL DEFAULT 0.00 CHECK (win_rate BETWEEN 0 AND 100),
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    notes           TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tipsters_active ON public.tipsters (active) WHERE active = TRUE;

-- -----------------------------------------------------------------------------
-- 4. Tabla: job_runs (Auditoría de GitHub Actions)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.job_runs (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_name          TEXT NOT NULL CHECK (job_name IN ('morning_fetch', 'night_grade')),
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at       TIMESTAMPTZ,
    status            TEXT NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'success', 'partial', 'failed')),
    matches_processed INTEGER NOT NULL DEFAULT 0,
    predictions_saved INTEGER NOT NULL DEFAULT 0,
    error_message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_runs_started_at ON public.job_runs (started_at DESC);

-- -----------------------------------------------------------------------------
-- 5. Trigger automático de updated_at
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_matches_updated_at ON public.matches;
CREATE TRIGGER trg_matches_updated_at
    BEFORE UPDATE ON public.matches
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_tipsters_updated_at ON public.tipsters;
CREATE TRIGGER trg_tipsters_updated_at
    BEFORE UPDATE ON public.tipsters
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- -----------------------------------------------------------------------------
-- 6. Row Level Security (RLS)
--    - Frontend (anon_key): SOLO lectura (SELECT).
--    - Escritura (INSERT/UPDATE/DELETE): reservada a service_role_key (bypass RLS).
-- -----------------------------------------------------------------------------
ALTER TABLE public.matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tipsters ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_runs ENABLE ROW LEVEL SECURITY;

-- Políticas de solo lectura para el cliente público (PWA)
DROP POLICY IF EXISTS "Public read matches" ON public.matches;
CREATE POLICY "Public read matches"
    ON public.matches
    FOR SELECT
    TO anon, authenticated
    USING (TRUE);

DROP POLICY IF EXISTS "Public read predictions" ON public.predictions;
CREATE POLICY "Public read predictions"
    ON public.predictions
    FOR SELECT
    TO anon, authenticated
    USING (TRUE);

DROP POLICY IF EXISTS "Public read tipsters" ON public.tipsters;
CREATE POLICY "Public read tipsters"
    ON public.tipsters
    FOR SELECT
    TO anon, authenticated
    USING (TRUE);

DROP POLICY IF EXISTS "Public read job_runs" ON public.job_runs;
CREATE POLICY "Public read job_runs"
    ON public.job_runs
    FOR SELECT
    TO anon, authenticated
    USING (TRUE);

-- -----------------------------------------------------------------------------
-- 7. Tablas de Combinadas (Parlays) + Políticas RLS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.parlays (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parlay_date   DATE NOT NULL UNIQUE,
    title         TEXT NOT NULL DEFAULT 'Combinada sugerida del día',
    total_odds    NUMERIC(8, 2) NOT NULL CHECK (total_odds > 1.00),
    adjusted_odds NUMERIC(8, 2),
    legs_count    INTEGER NOT NULL CHECK (legs_count BETWEEN 2 AND 3),
    result        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (result IN ('pending', 'won', 'lost', 'void')),
    graded_at     TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parlays_date ON public.parlays (parlay_date DESC);
CREATE INDEX IF NOT EXISTS idx_parlays_result ON public.parlays (result);

CREATE TABLE IF NOT EXISTS public.parlay_legs (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parlay_id     BIGINT NOT NULL REFERENCES public.parlays(id) ON DELETE CASCADE,
    prediction_id BIGINT NOT NULL REFERENCES public.predictions(id) ON DELETE CASCADE,
    leg_odds      NUMERIC(6, 2) NOT NULL CHECK (leg_odds > 1.00),
    leg_order     INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT uq_parlay_legs_pair UNIQUE (parlay_id, prediction_id)
);

CREATE INDEX IF NOT EXISTS idx_parlay_legs_parlay_id ON public.parlay_legs (parlay_id);

ALTER TABLE public.parlays ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.parlay_legs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public read parlays" ON public.parlays;
CREATE POLICY "Public read parlays"
    ON public.parlays
    FOR SELECT
    TO anon, authenticated
    USING (TRUE);

DROP POLICY IF EXISTS "Public read parlay_legs" ON public.parlay_legs;
CREATE POLICY "Public read parlay_legs"
    ON public.parlay_legs
    FOR SELECT
    TO anon, authenticated
    USING (TRUE);
