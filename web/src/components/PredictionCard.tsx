"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, ShieldCheck, Sparkles } from "lucide-react";
import type { PredictionWithMatch } from "@/lib/supabase";
import { formatOutcomeLabel, getSourceBadgeText } from "@/lib/formatters";
import { LocalTime } from "@/components/LocalTime";

interface PredictionCardProps {
  prediction: PredictionWithMatch;
}

const STATUS_STYLES: Record<
  PredictionWithMatch["result"],
  { label: string; bg: string; text: string }
> = {
  pending: { label: "Pendiente", bg: "bg-[#FEF3C7]", text: "text-[#D97706]" },
  won: { label: "Acertado", bg: "bg-[#D1FAE5]", text: "text-[#059669]" },
  lost: { label: "Fallado", bg: "bg-[#FEE2E2]", text: "text-[#DC2626]" },
  void: { label: "Anulado", bg: "bg-[#F1F5F9]", text: "text-[#475569]" },
};

export function PredictionCard({ prediction }: PredictionCardProps) {
  const [expanded, setExpanded] = useState(false);
  const match = prediction.matches;
  if (!match) return null;

  const statusStyle = STATUS_STYLES[prediction.result];
  const sourceBadge = getSourceBadgeText(
    prediction.source_type,
    prediction.source_name,
    prediction.consensus_pct
  );

  return (
    <article className="overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-sm">
      {/* Vista Principal: lectura completa en <3 segundos */}
      <div className="p-4">
        {/* Encabezado: Liga + Hora local + Estado */}
        <div className="mb-2.5 flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2 text-xs font-semibold text-slate-500">
            <span className="truncate uppercase tracking-wide text-[#0969DA]">
              {match.league}
            </span>
            <span aria-hidden="true">·</span>
            <span className="whitespace-nowrap text-slate-600">
              <LocalTime iso={match.start_time} mode="match" />
            </span>
          </div>
          <span
            className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold ${statusStyle.bg} ${statusStyle.text}`}
          >
            {statusStyle.label}
          </span>
        </div>

        {/* Equipos */}
        <h2 className="mb-3 text-[17px] font-bold leading-snug text-slate-900">
          {match.home_team}{" "}
          <span className="font-normal text-slate-400">vs</span>{" "}
          {match.away_team}
        </h2>

        {/* Recuadro destacado del pronóstico en español claro */}
        <div className="rounded-xl border border-blue-100 bg-blue-50/70 p-3.5">
          <p className="text-[11px] font-bold uppercase tracking-wider text-[#0969DA]">
            Pronóstico recomendado
          </p>
          <p className="mt-1 text-lg font-extrabold leading-tight text-slate-900">
            {prediction.pick_label_es}
          </p>

          <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 text-xs font-semibold text-slate-700">
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-white px-2.5 py-1 text-slate-700 shadow-xs">
              <ShieldCheck className="h-3.5 w-3.5 text-[#059669]" />
              {sourceBadge}
            </span>
            <span className="rounded-lg bg-white px-2.5 py-1 font-bold text-slate-900 shadow-xs">
              Cuota: {Number(prediction.odds).toFixed(2)}
            </span>
          </div>
        </div>
      </div>

      {/* Botón táctil >=48px de Divulgación Progresiva */}
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        className="flex min-h-[48px] w-full items-center justify-center gap-1.5 border-t border-slate-100 bg-slate-50/80 px-4 text-sm font-semibold text-slate-600 transition-colors active:bg-slate-100 hover:bg-slate-100"
      >
        <span>{expanded ? "Ocultar detalle" : "Ver detalle"}</span>
        {expanded ? (
          <ChevronUp className="h-4 w-4" />
        ) : (
          <ChevronDown className="h-4 w-4" />
        )}
      </button>

      {/* Bloque Desplegable: soporte técnico oculto por defecto */}
      {expanded && (
        <div className="space-y-4 border-t border-slate-100 bg-slate-50/50 px-4 py-4 text-sm text-slate-700">
          {/* Desglose de votos de la comunidad */}
          {prediction.vote_breakdown && prediction.vote_breakdown.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">
                Desglose de votos ({prediction.market_raw})
              </p>
              <div className="space-y-2">
                {prediction.vote_breakdown.map((item) => {
                  const pct = Math.max(0, Math.min(100, Number(item.pct) || 0));
                  return (
                    <div key={item.outcome}>
                      <div className="mb-1 flex justify-between text-xs font-medium text-slate-700">
                        <span>
                          {formatOutcomeLabel(
                            item.outcome,
                            match.home_team,
                            match.away_team
                          )}
                        </span>
                        <span className="font-bold">{pct}%</span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
                        <div
                          className="h-full rounded-full bg-[#0969DA] transition-all"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Racha reciente si está disponible */}
          {(match.home_form || match.away_form) && (
            <div>
              <p className="mb-1.5 text-xs font-bold uppercase tracking-wide text-slate-500">
                Racha reciente
              </p>
              <div className="space-y-1 text-xs">
                {match.home_form && (
                  <p>
                    <span className="font-semibold text-slate-800">
                      {match.home_team}:
                    </span>{" "}
                    {match.home_form}
                  </p>
                )}
                {match.away_form && (
                  <p>
                    <span className="font-semibold text-slate-800">
                      {match.away_team}:
                    </span>{" "}
                    {match.away_form}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Justificación breve (cuando esté disponible) */}
          {prediction.short_reason && (
            <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs leading-relaxed text-slate-700">
              <p className="mb-1 flex items-center gap-1 font-bold text-slate-800">
                <Sparkles className="h-3.5 w-3.5 text-[#0969DA]" />
                Resumen del pronóstico
              </p>
              <p>{prediction.short_reason}</p>
            </div>
          )}

          {/* Metadatos compactos */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200/70 pt-2.5 text-xs text-slate-500">
            <span>
              Mercado: <strong className="text-slate-700">{prediction.market_raw}</strong>
            </span>
            <span>
              Confianza:{" "}
              <strong className="text-slate-700">
                {prediction.confidence_rank}/10
              </strong>
            </span>
          </div>
        </div>
      )}
    </article>
  );
}
