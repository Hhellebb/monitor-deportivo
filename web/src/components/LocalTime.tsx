"use client";

import { useSyncExternalStore } from "react";
import {
  formatHeaderDate,
  formatMatchLocalTime,
  formatResultDate,
} from "@/lib/formatters";

interface LocalTimeProps {
  iso?: string;
  mode: "header" | "match" | "result" | "updated";
}

const emptySubscribe = () => () => {};

function useIsClient(): boolean {
  return useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false
  );
}

export function LocalTime({ iso, mode }: LocalTimeProps) {
  const isClient = useIsClient();

  if (!isClient) {
    return (
      <span className="inline-block h-4 w-20 rounded bg-slate-200/70 align-middle" />
    );
  }

  const now = new Date();
  let label = "";

  if (mode === "header") {
    label = formatHeaderDate(now);
  } else if (iso) {
    if (mode === "match") {
      label = formatMatchLocalTime(iso, now);
    } else if (mode === "result") {
      label = formatResultDate(iso);
    } else if (mode === "updated") {
      const dt = new Date(iso);
      if (!Number.isNaN(dt.getTime())) {
        const timeStr = new Intl.DateTimeFormat("es-MX", {
          hour: "numeric",
          minute: "2-digit",
          hour12: true,
        }).format(dt);
        label = `Act. ${timeStr}`;
      }
    }
  }

  return <span>{label}</span>;
}
