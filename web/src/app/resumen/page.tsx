import { SummaryView } from "@/components/SummaryView";
import {
  getSupabasePublicClient,
  type PredictionWithMatch,
} from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function ResumenPage() {
  const supabase = getSupabasePublicClient();

  const { data } = await supabase
    .from("predictions")
    .select("*, matches(*)")
    .in("result", ["won", "lost", "void"])
    .order("graded_at", { ascending: false })
    .limit(500);

  const graded = ((data ?? []) as unknown as PredictionWithMatch[]).filter(
    (p) => p.matches !== null
  );

  return <SummaryView graded={graded} />;
}
