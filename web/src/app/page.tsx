import { TodayView } from "@/components/TodayView";
import {
  getSupabasePublicClient,
  type PredictionWithMatch,
} from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const supabase = getSupabasePublicClient();

  const [predsRes, runRes] = await Promise.all([
    supabase
      .from("predictions")
      .select("*, matches(*)")
      .eq("result", "pending")
      .order("confidence_rank", { ascending: false })
      .limit(20),
    supabase
      .from("job_runs")
      .select("finished_at, started_at")
      .eq("job_name", "morning_fetch")
      .in("status", ["success", "partial"])
      .order("id", { ascending: false })
      .limit(1),
  ]);

  const rawList = (predsRes.data ?? []) as unknown as PredictionWithMatch[];

  // Ordenar por confianza y luego por hora de inicio más próxima
  const predictions = rawList
    .filter((p) => p.matches !== null)
    .sort((a, b) => {
      const timeA = new Date(a.matches!.start_time).getTime();
      const timeB = new Date(b.matches!.start_time).getTime();
      if (timeA !== timeB) return timeA - timeB;
      return b.confidence_rank - a.confidence_rank;
    });

  const lastRun = runRes.data?.[0];
  const lastUpdatedIso = lastRun?.finished_at ?? lastRun?.started_at ?? null;

  return (
    <TodayView predictions={predictions} lastUpdatedIso={lastUpdatedIso} />
  );
}
