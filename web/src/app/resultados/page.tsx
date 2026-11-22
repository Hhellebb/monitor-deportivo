import { ResultsView } from "@/components/ResultsView";
import {
  getSupabasePublicClient,
  type ParlayWithLegs,
  type PredictionWithMatch,
} from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function ResultadosPage() {
  const supabase = getSupabasePublicClient();

  const since = new Date();
  since.setDate(since.getDate() - 35);

  const [predsRes, parlaysRes] = await Promise.all([
    supabase
      .from("predictions")
      .select("*, matches(*)")
      .in("result", ["won", "lost", "void"])
      .gte("created_at", since.toISOString())
      .order("graded_at", { ascending: false })
      .limit(150),
    supabase
      .from("parlays")
      .select("*, parlay_legs(id, leg_odds, leg_order, predictions(*, matches(*)))")
      .in("result", ["won", "lost", "void"])
      .order("parlay_date", { ascending: false })
      .limit(10),
  ]);

  const results = ((predsRes.data ?? []) as unknown as PredictionWithMatch[])
    .filter((p) => p.matches !== null)
    .sort((a, b) => {
      const timeA = new Date(a.matches!.start_time).getTime();
      const timeB = new Date(b.matches!.start_time).getTime();
      return timeB - timeA;
    });

  const parlays = (parlaysRes.data ?? []) as unknown as ParlayWithLegs[];

  return <ResultsView results={results} parlays={parlays} />;
}
