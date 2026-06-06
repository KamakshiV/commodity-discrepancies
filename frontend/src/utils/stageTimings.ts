import { formatAnalysisDuration } from "./formatDuration";

const STAGE_LABELS: Record<string, string> = {
  data_load: "Data load",
  rule_engine: "Rule engine",
  ai_agent: "AI agents",
  pdf: "PDF build",
};

/** Human-readable per-stage timing line for results UI. */
export function formatStageTimings(timings: Record<string, number>): string | null {
  const order = ["data_load", "rule_engine", "ai_agent", "pdf"];
  const parts = order
    .filter((key) => timings[key] != null && timings[key] > 0)
    .map((key) => `${STAGE_LABELS[key] ?? key}: ${formatAnalysisDuration(timings[key])}`);

  return parts.length > 0 ? parts.join(" · ") : null;
}
