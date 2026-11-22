import { createClient } from "@supabase/supabase-js";

export interface VoteBreakdownItem {
  outcome: string;
  pct: number;
}

export interface MatchRow {
  id: string;
  external_url: string;
  sport: string;
  league: string;
  home_team: string;
  away_team: string;
  start_time: string;
  status: "pending" | "live" | "finished" | "postponed" | "cancelled";
  final_score: string | null;
  home_score: number | null;
  away_score: number | null;
  partial_results: string | null;
  home_form: string | null;
  away_form: string | null;
  updated_at: string;
}

export interface PredictionWithMatch {
  id: number;
  match_id: string;
  source_type: "community" | "tipster" | "hybrid";
  source_name: string;
  market_raw: string;
  pick_raw: string;
  pick_label_es: string;
  odds: number;
  bookmaker?: string;
  consensus_pct: number | null;
  vote_breakdown: VoteBreakdownItem[] | null;
  short_reason: string | null;
  confidence_rank: number;
  result: "pending" | "won" | "lost" | "void";
  graded_at: string | null;
  created_at: string;
  matches: MatchRow | null;
}

export interface ParlayLegWithPrediction {
  id: number;
  leg_odds: number;
  leg_order: number;
  predictions: PredictionWithMatch | null;
}

export interface ParlayWithLegs {
  id: number;
  parlay_date: string;
  title: string;
  total_odds: number;
  adjusted_odds: number | null;
  legs_count: number;
  result: "pending" | "won" | "lost" | "void";
  graded_at: string | null;
  parlay_legs: ParlayLegWithPrediction[];
}

export interface JobRunRow {
  id: number;
  job_name: "morning_fetch" | "night_grade";
  started_at: string;
  finished_at: string | null;
  status: "running" | "success" | "partial" | "failed";
  matches_processed: number;
  predictions_saved: number;
}

export function getSupabasePublicClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !anonKey) {
    throw new Error(
      "Faltan NEXT_PUBLIC_SUPABASE_URL y/o NEXT_PUBLIC_SUPABASE_ANON_KEY."
    );
  }

  return createClient(url, anonKey, {
    auth: { persistSession: false },
  });
}
