import { ResultsView } from "@/components/ResultsView";
import {
  getSupabasePublicClient,
  type PredictionWithMatch,
} from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function ResultadosPage() {
  const supabase = getSupabasePublicClient();

  // Traer los últimos 35 días de pronósticos ya calificados
  const since = new Date();
  since.setDate(since.getDate() - 35);

  const { data } = await supabase
    .from("predictions")
    .select("*, matches(*)")
    .in("result", ["won", "lost", "void"])
    .gte("created_at", since.toISOString())
    .order("graded_at", { ascending: false })
    .limit(150);

  const results = ((data ?? []) as unknown as PredictionWithMatch[])
    .filter((p) => p.matches !== null)
    .sort((a, b) => {
      const timeA = new Date(a.matches!.start_time).getTime();
      const timeB = new Date(b.matches!.start_time).getTime();
      return timeB - timeA;
    });

  return <ResultsView results={results} />;
}
