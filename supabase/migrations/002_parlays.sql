-- =============================================================================
-- Migración 002: Tablas parlays y parlay_legs + columna bookmaker en predictions
-- =============================================================================

ALTER TABLE public.predictions
    ADD COLUMN IF NOT EXISTS bookmaker TEXT NOT NULL DEFAULT 'bet365';

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

-- RLS (Solo SELECT para anon/authenticated; escritura exclusiva service_role)
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
