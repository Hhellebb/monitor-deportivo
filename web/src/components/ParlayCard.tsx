"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Layers } from "lucide-react";
import type { ParlayWithLegs } from "@/lib/supabase";
import { LocalTime } from "@/components/LocalTime";

interface ParlayCardProps {
  parlay: ParlayWithLegs;
}

const RESULT_BADGE: Record<
  ParlayWithLegs["result"],
  { label: string; bg: string; text: string }
> = {
  pending: { label: "Activa", bg: "bg-[#FEF3C7]", text: "text-[#D97706]" },
  won: { label: "ACERTADA", bg: "bg-[#D1FAE5]", text: "text-[#059669]" },
  lost: { label: "FALLADA", bg: "bg-[#FEE2E2]", text: "text-[#DC2626]" },
  void: { label: "ANULADA", bg: "bg-[#F1F5F9]", text: "text-[#475569]" },
};

export function ParlayCard({ parlay }: ParlayCardProps) {
  const [open, setOpen] = useState(true);
  const legs = [...(parlay.parlay_legs ?? [])]
    .filter((l) => l.predictions?.matches)
    .sort((a, b) => a.leg_order - b.leg_order);

  if (legs.length === 0) return null;

  const badge = RESULT_BADGE[parlay.result];
  const displayOdds = Number(parlay.adjusted_odds ?? parlay.total_odds).toFixed(2);
  const wasAdjusted =
    parlay.adjusted_odds !== null &&
    Number(parlay.adjusted_odds) !== Number(parlay.total_odds);

  return (
    <section className="overflow-hidden rounded-2xl border-2 border-[#0969DA]/25 bg-gradient-to-b from-blue-50/80 to-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex min-h-[56px] w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#0969DA] text-white">
            <Layers className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-sm font-extrabold text-slate-900">
                Combinada sugerida del día
              </h2>
              <span
                className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-extrabold ${badge.bg} ${badge.text}`}
              >
                {badge.label}
              </span>
            </div>
            <p className="text-xs font-semibold text-slate-600">
              {legs.length} selecciones · Momio total:{" "}
              <strong className="text-[#0969DA]">{displayOdds}</strong>
              {wasAdjusted && (
                <span className="ml-1 text-[11px] font-normal text-slate-500">
                  (ajustado)
                </span>
              )}
            </p>
          </div>
        </div>
        {open ? (
          <ChevronUp className="h-5 w-5 shrink-0 text-slate-500" />
        ) : (
          <ChevronDown className="h-5 w-5 shrink-0 text-slate-500" />
        )}
      </button>

      {open && (
        <div className="space-y-2 border-t border-blue-100/80 px-4 pb-4 pt-3">
          {legs.map((leg, idx) => {
            const pred = leg.predictions!;
            const match = pred.matches!;
            return (
              <div
                key={leg.id}
                className="flex items-start justify-between gap-3 rounded-xl border border-slate-200/80 bg-white px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
                    {idx + 1}. {match.league} ·{" "}
                    <LocalTime iso={match.start_time} mode="match" />
                  </p>
                  <p className="truncate text-xs font-semibold text-slate-700">
                    {match.home_team} vs {match.away_team}
                  </p>
                  <p className="mt-0.5 text-sm font-extrabold text-slate-900">
                    {pred.pick_label_es}
                  </p>
                </div>
                <span className="shrink-0 rounded-lg bg-slate-100 px-2 py-1 text-xs font-extrabold text-slate-800">
                  {Number(leg.leg_odds).toFixed(2)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
