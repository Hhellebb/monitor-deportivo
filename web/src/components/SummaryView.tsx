"use client";

import { Award, CheckCircle2, TrendingUp, Users } from "lucide-react";
import type { PredictionWithMatch } from "@/lib/supabase";
import { getSportLabelEs } from "@/lib/formatters";

interface SummaryViewProps {
  graded: PredictionWithMatch[];
}

interface BucketStats {
  label: string;
  won: number;
  lost: number;
  pct: number;
}

function buildBuckets(
  items: PredictionWithMatch[],
  getKey: (p: PredictionWithMatch) => string
): BucketStats[] {
  const map = new Map<string, { won: number; lost: number }>();

  for (const item of items) {
    if (item.result !== "won" && item.result !== "lost") continue;
    const key = getKey(item);
    const cur = map.get(key) ?? { won: 0, lost: 0 };
    if (item.result === "won") cur.won += 1;
    else cur.lost += 1;
    map.set(key, cur);
  }

  return Array.from(map.entries())
    .map(([label, { won, lost }]) => {
      const total = won + lost;
      return {
        label,
        won,
        lost,
        pct: total > 0 ? Math.round((won / total) * 100) : 0,
      };
    })
    .sort((a, b) => b.pct - a.pct || b.won - a.won);
}

export function SummaryView({ graded }: SummaryViewProps) {
  const decided = graded.filter(
    (g) => g.result === "won" || g.result === "lost"
  );
  const won = decided.filter((g) => g.result === "won").length;
  const lost = decided.filter((g) => g.result === "lost").length;
  const voidCount = graded.filter((g) => g.result === "void").length;
  const globalPct = decided.length > 0 ? Math.round((won / decided.length) * 100) : null;

  const byLeague = buildBuckets(decided, (p) => p.matches?.league ?? "General");
  const bestLeague = byLeague[0] ?? null;

  const bySport = buildBuckets(decided, (p) =>
    getSportLabelEs(p.matches?.sport ?? "Otro")
  );

  const bySource = buildBuckets(decided, (p) => {
    if (p.source_type === "community") return "Consenso Comunitario";
    if (p.source_type === "tipster") return "Tipsters Individuales";
    return "Híbrido (Comunidad + Tipster)";
  });

  return (
    <div className="flex flex-col">
      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/95 px-4 py-4 backdrop-blur-md">
        <h1 className="text-xl font-extrabold tracking-tight text-slate-900">
          Resumen de Efectividad
        </h1>
        <p className="mt-0.5 text-xs font-medium text-slate-500">
          Rendimiento acumulado de pronósticos calificados
        </p>
      </header>

      <div className="space-y-4 px-4 pt-4">
        {/* Panel de 3 KPIs principales */}
        <section className="grid grid-cols-1 gap-3">
          {/* KPI 1: Porcentaje de Acierto Global */}
          <div className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-xs">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wide text-slate-500">
                Acierto Global
              </span>
              <TrendingUp className="h-5 w-5 text-[#059669]" />
            </div>
            <p className="mt-2 text-4xl font-extrabold tracking-tight text-slate-900">
              {globalPct !== null ? `${globalPct}%` : "—"}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {decided.length > 0
                ? `Basado en ${decided.length} pronósticos definidos${
                    voidCount > 0 ? ` (${voidCount} anulados)` : ""
                  }`
                : "Se calculará automáticamente tras la primera calificación nocturna."}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            {/* KPI 2: Balance de Resultados */}
            <div className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-xs">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
                  Balance
                </span>
                <CheckCircle2 className="h-4 w-4 text-[#0969DA]" />
              </div>
              <p className="mt-2 text-lg font-extrabold text-slate-900">
                <span className="text-[#059669]">{won}</span>
                <span className="mx-1 text-slate-300">/</span>
                <span className="text-[#DC2626]">{lost}</span>
              </p>
              <p className="mt-0.5 text-xs text-slate-500">
                Acertados / Fallados
              </p>
            </div>

            {/* KPI 3: Mejor Liga/Deporte */}
            <div className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-xs">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
                  Mejor Liga
                </span>
                <Award className="h-4 w-4 text-[#D97706]" />
              </div>
              <p className="mt-2 truncate text-base font-extrabold text-slate-900">
                {bestLeague ? bestLeague.label : "—"}
              </p>
              <p className="mt-0.5 text-xs font-semibold text-[#059669]">
                {bestLeague
                  ? `${bestLeague.pct}% (${bestLeague.won}/${
                      bestLeague.won + bestLeague.lost
                    })`
                  : "Pendiente"}
              </p>
            </div>
          </div>
        </section>

        {/* Efectividad por Deporte (Barras horizontales simples) */}
        <section className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-xs">
          <h2 className="mb-3 text-sm font-extrabold text-slate-900">
            Efectividad por Deporte
          </h2>
          {bySport.length === 0 ? (
            <p className="text-xs text-slate-500">
              Aquí verás las barras de efectividad en cuanto se califiquen los
              primeros partidos.
            </p>
          ) : (
            <div className="space-y-3">
              {bySport.map((row) => (
                <div key={row.label}>
                  <div className="mb-1 flex items-center justify-between text-xs font-semibold">
                    <span className="text-slate-800">{row.label}</span>
                    <span className="text-slate-600">
                      <strong className="text-slate-900">{row.pct}%</strong> (
                      {row.won}G - {row.lost}P)
                    </span>
                  </div>
                  <div className="h-3 w-full overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full rounded-full bg-[#059669] transition-all"
                      style={{ width: `${row.pct}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Rendimiento por Fuente */}
        <section className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-xs">
          <div className="mb-3 flex items-center gap-2">
            <Users className="h-4 w-4 text-[#0969DA]" />
            <h2 className="text-sm font-extrabold text-slate-900">
              Rendimiento por Fuente
            </h2>
          </div>
          {bySource.length === 0 ? (
            <p className="text-xs text-slate-500">
              Comparativa entre Consenso Comunitario y Tipsters disponible al
              cerrar las primeras jornadas.
            </p>
          ) : (
            <div className="space-y-2.5">
              {bySource.map((src) => (
                <div
                  key={src.label}
                  className="flex items-center justify-between rounded-xl bg-slate-50 px-3.5 py-3"
                >
                  <div>
                    <p className="text-sm font-bold text-slate-900">
                      {src.label}
                    </p>
                    <p className="text-xs text-slate-500">
                      {src.won} acertados · {src.lost} fallados
                    </p>
                  </div>
                  <span className="rounded-lg bg-white px-2.5 py-1 text-sm font-extrabold text-[#0969DA] shadow-xs">
                    {src.pct}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
