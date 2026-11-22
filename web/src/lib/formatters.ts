export type SportFilterKey =
  | "all"
  | "football"
  | "basketball"
  | "baseball"
  | "american-football";

export const SPORT_FILTERS: { key: SportFilterKey; label: string }[] = [
  { key: "all", label: "Todos" },
  { key: "football", label: "Fútbol" },
  { key: "basketball", label: "NBA" },
  { key: "baseball", label: "Béisbol" },
  { key: "american-football", label: "NFL" },
];

export function getSportLabelEs(sport: string): string {
  switch (sport.toLowerCase()) {
    case "football":
    case "soccer":
      return "Fútbol";
    case "basketball":
      return "NBA";
    case "baseball":
      return "Béisbol";
    case "american-football":
      return "NFL";
    default:
      return sport;
  }
}

export function getLocalDateKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function formatHeaderDate(date: Date): string {
  const formatted = new Intl.DateTimeFormat("es-MX", {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(date);
  return formatted.replace(/\./g, "").replace(/^./, (c) => c.toUpperCase());
}

export function formatMatchLocalTime(isoUtc: string, now: Date = new Date()): string {
  const dt = new Date(isoUtc);
  if (Number.isNaN(dt.getTime())) return "";

  const timeStr = new Intl.DateTimeFormat("es-MX", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(dt);

  const todayKey = getLocalDateKey(now);
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  const tomorrowKey = getLocalDateKey(tomorrow);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const yesterdayKey = getLocalDateKey(yesterday);

  const targetKey = getLocalDateKey(dt);
  if (targetKey === todayKey) return `Hoy · ${timeStr}`;
  if (targetKey === tomorrowKey) return `Mañana · ${timeStr}`;
  if (targetKey === yesterdayKey) return `Ayer · ${timeStr}`;

  const shortDay = new Intl.DateTimeFormat("es-MX", {
    weekday: "short",
    day: "numeric",
    month: "short",
  })
    .format(dt)
    .replace(/\./g, "");
  const cap = shortDay.charAt(0).toUpperCase() + shortDay.slice(1);
  return `${cap} · ${timeStr}`;
}

export function formatResultDate(isoUtc: string): string {
  const dt = new Date(isoUtc);
  if (Number.isNaN(dt.getTime())) return "";
  const str = new Intl.DateTimeFormat("es-MX", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  })
    .format(dt)
    .replace(/\./g, "");
  return str.charAt(0).toUpperCase() + str.slice(1);
}

export function formatOutcomeLabel(
  outcome: string,
  homeTeam: string,
  awayTeam: string
): string {
  const clean = outcome.trim().toLowerCase();
  if (clean === "1" || clean === "home") return homeTeam;
  if (clean === "x" || clean === "draw") return "Empate";
  if (clean === "2" || clean === "away") return awayTeam;
  return outcome;
}

export function getSourceBadgeText(
  sourceType: "community" | "tipster" | "hybrid",
  sourceName: string,
  consensusPct: number | null
): string {
  if (sourceType === "hybrid" && consensusPct !== null) {
    return `${consensusPct}% comunidad + Tipster`;
  }
  if (sourceType === "community" && consensusPct !== null) {
    return `${consensusPct}% comunidad`;
  }
  if (sourceType === "tipster") {
    return `Tipster: ${sourceName}`;
  }
  return "Pick Destacado";
}
