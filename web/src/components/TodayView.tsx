"use client";

import { useMemo, useState } from "react";
import { RefreshCw, Trophy } from "lucide-react";
import { useRouter } from "next/navigation";
import type { ParlayWithLegs, PredictionWithMatch } from "@/lib/supabase";
import { SPORT_FILTERS, type SportFilterKey } from "@/lib/formatters";
import { LocalTime } from "@/components/LocalTime";
import { ParlayCard } from "@/components/ParlayCard";
import { PredictionCard } from "@/components/PredictionCard";

interface TodayViewProps {
  predictions: PredictionWithMatch[];
  dailyParlay: ParlayWithLegs | null;
  lastUpdatedIso: string | null;
}

export function TodayView({
  predictions,
  dailyParlay,
  lastUpdatedIso,
}: TodayViewProps) {
  const [selectedSport, setSelectedSport] = useState<SportFilterKey>("all");
  const [refreshing, setRefreshing] = useState(false);
  const router = useRouter();

  const filtered = useMemo(() => {
    const valid = predictions.filter((p) => p.matches !== null);
    if (selectedSport === "all") return valid;
    return valid.filter((p) => p.matches?.sport.toLowerCase() === selectedSport);
  }, [predictions, selectedSport]);

  const handleRefresh = () => {
    setRefreshing(true);
    router.refresh();
    setTimeout(() => setRefreshing(false), 600);
  };

  return (
    <div className="flex flex-col">
      {/* Cabecera Superior */}
      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/95 px-4 pb-3 pt-4 backdrop-blur-md">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-extrabold tracking-tight text-slate-900">
              Monitor Deportivo
            </h1>
            <div className="mt-0.5 flex items-center gap-2 text-xs font-medium text-slate-500">
              <LocalTime mode="header" />
              {lastUpdatedIso && (
                <>
                  <span aria-hidden="true">·</span>
                  <LocalTime iso={lastUpdatedIso} mode="updated" />
                </>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={handleRefresh}
            aria-label="Actualizar pronósticos"
            className="flex h-12 w-12 items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-slate-700 active:bg-slate-100"
          >
            <RefreshCw className={`h-5 w-5 ${refreshing ? "animate-spin" : ""}`} />
          </button>
        </div>

        {/* Fila deslizante de botones de filtrado rápido (>=48px alto) */}
        <div
          role="tablist"
          aria-label="Filtrar por deporte"
          className="no-scrollbar -mx-4 mt-3 flex gap-2 overflow-x-auto px-4 pb-0.5"
        >
          {SPORT_FILTERS.map((f) => {
            const active = selectedSport === f.key;
            const count =
              f.key === "all"
                ? predictions.length
                : predictions.filter(
                    (p) => p.matches?.sport.toLowerCase() === f.key
                  ).length;

            return (
              <button
                key={f.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setSelectedSport(f.key)}
                className={`flex min-h-[48px] shrink-0 items-center gap-1.5 rounded-xl px-4 text-sm font-bold transition-colors ${
                  active
                    ? "bg-[#0969DA] text-white shadow-xs"
                    : "border border-slate-200 bg-white text-slate-700 active:bg-slate-100"
                }`}
              >
                <span>{f.label}</span>
                {count > 0 && (
                  <span
                    className={`rounded-full px-1.5 py-0.5 text-[11px] ${
                      active
                        ? "bg-white/20 text-white"
                        : "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </header>

      {/* Lista vertical de tarjetas */}
      <section className="space-y-3.5 px-4 pt-4">
        {/* Bloque destacado opcional: Combinada sugerida del día */}
        {selectedSport === "all" && dailyParlay && (
          <ParlayCard parlay={dailyParlay} />
        )}

        {filtered.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-5 py-10 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-500">
              <Trophy className="h-6 w-6" />
            </div>
            <h2 className="text-base font-bold text-slate-900">
              Sin pronósticos activos aquí
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              {selectedSport === "all"
                ? "Los próximos picks se actualizan automáticamente cada mañana a las 7:00 a. m."
                : "No hay partidos recomendados para este deporte en la jornada actual."}
            </p>
          </div>
        ) : (
          filtered.map((pred) => (
            <PredictionCard key={pred.id} prediction={pred} />
          ))
        )}
      </section>
    </div>
  );
}
