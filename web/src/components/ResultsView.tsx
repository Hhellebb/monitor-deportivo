"use client";

import { useMemo, useState } from "react";
import { Clock } from "lucide-react";
import type { PredictionWithMatch } from "@/lib/supabase";
import { getLocalDateKey } from "@/lib/formatters";
import { LocalTime } from "@/components/LocalTime";

type TimeRangeKey = "yesterday" | "7days" | "month";

const RANGES: { key: TimeRangeKey; label: string }[] = [
  { key: "yesterday", label: "Ayer" },
  { key: "7days", label: "Últimos 7 días" },
  { key: "month", label: "Este mes" },
];

const BADGE_MAP: Record<
  "won" | "lost" | "void",
  { label: string; bg: string; text: string; border: string }
> = {
  won: {
    label: "ACERTADO",
    bg: "bg-[#D1FAE5]",
    text: "text-[#059669]",
    border: "border-[#059669]/20",
  },
  lost: {
    label: "FALLADO",
    bg: "bg-[#FEE2E2]",
    text: "text-[#DC2626]",
    border: "border-[#DC2626]/20",
  },
  void: {
    label: "ANULADO",
    bg: "bg-[#F1F5F9]",
    text: "text-[#475569]",
    border: "border-slate-300",
  },
};

interface ResultsViewProps {
  results: PredictionWithMatch[];
}

export function ResultsView({ results }: ResultsViewProps) {
  const [range, setRange] = useState<TimeRangeKey>("7days");

  const filtered = useMemo(() => {
    const now = new Date();
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    const yesterdayKey = getLocalDateKey(yesterday);

    const sevenDaysAgo = new Date(now);
    sevenDaysAgo.setDate(now.getDate() - 7);

    const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);

    return results.filter((item) => {
      if (!item.matches) return false;
      const dt = new Date(item.matches.start_time);
      if (Number.isNaN(dt.getTime())) return false;

      if (range === "yesterday") {
        return getLocalDateKey(dt) === yesterdayKey;
      }
      if (range === "7days") {
        return dt >= sevenDaysAgo;
      }
      return dt >= startOfMonth;
    });
  }, [results, range]);

  const wonCount = filtered.filter((r) => r.result === "won").length;
  const lostCount = filtered.filter((r) => r.result === "lost").length;

  return (
    <div className="flex flex-col">
      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/95 px-4 pb-3 pt-4 backdrop-blur-md">
        <div className="flex items-baseline justify-between">
          <h1 className="text-xl font-extrabold tracking-tight text-slate-900">
            Resultados
          </h1>
          {filtered.length > 0 && (
            <span className="text-xs font-bold text-slate-500">
              {wonCount} acertados · {lostCount} fallados
            </span>
          )}
        </div>

        {/* Selector de 3 posiciones (>=48px alto) */}
        <div
          role="tablist"
          aria-label="Rango de tiempo"
          className="mt-3 grid grid-cols-3 gap-1.5 rounded-xl bg-slate-100 p-1"
        >
          {RANGES.map((r) => {
            const active = range === r.key;
            return (
              <button
                key={r.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setRange(r.key)}
                className={`min-h-[48px] rounded-lg px-2 text-xs font-bold transition-all ${
                  active
                    ? "bg-white text-[#0969DA] shadow-xs"
                    : "text-slate-600 active:bg-slate-200/60"
                }`}
              >
                {r.label}
              </button>
            );
          })}
        </div>
      </header>

      {/* Lista Histórica Compacta */}
      <section className="space-y-3 px-4 pt-4">
        {filtered.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-5 py-10 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-500">
              <Clock className="h-6 w-6" />
            </div>
            <h2 className="text-base font-bold text-slate-900">
              Aún sin resultados en este periodo
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Los partidos del día se califican automáticamente cada noche a las
              11:30 p. m.
            </p>
          </div>
        ) : (
          filtered.map((item) => {
            const match = item.matches!;
            const badge =
              item.result === "won" || item.result === "lost"
                ? BADGE_MAP[item.result]
                : BADGE_MAP.void;

            return (
              <article
                key={item.id}
                className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-xs"
              >
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-1.5 text-xs font-semibold text-slate-500">
                    <span className="truncate uppercase text-[#0969DA]">
                      {match.league}
                    </span>
                    <span>·</span>
                    <span className="whitespace-nowrap">
                      <LocalTime iso={match.start_time} mode="result" />
                    </span>
                  </div>
                  <span
                    className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-extrabold tracking-wide ${badge.bg} ${badge.text} ${badge.border}`}
                  >
                    {badge.label}
                  </span>
                </div>

                {/* Equipos + Marcador Final prominente */}
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-[15px] font-bold text-slate-900">
                      {match.home_team}
                    </p>
                    <p className="truncate text-[15px] font-bold text-slate-900">
                      {match.away_team}
                    </p>
                  </div>
                  <div className="shrink-0 rounded-xl bg-slate-900 px-3.5 py-2 text-center text-lg font-extrabold tracking-wider text-white">
                    {match.final_score ?? "—"}
                  </div>
                </div>

                {/* Pronóstico que se había dado */}
                <div className="mt-3 flex items-center justify-between gap-2 border-t border-slate-100 pt-2.5 text-xs">
                  <span className="font-semibold text-slate-700">
                    Pick:{" "}
                    <strong className="text-slate-900">
                      {item.pick_label_es}
                    </strong>
                  </span>
                  <span className="shrink-0 font-bold text-slate-600">
                    Cuota {Number(item.odds).toFixed(2)}
                  </span>
                </div>
              </article>
            );
          })
        )}
      </section>
    </div>
  );
}
