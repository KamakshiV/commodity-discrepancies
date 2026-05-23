import type { LlmModelOption } from "../types";

/** Fallback when /api/config/llm is unavailable (backend offline). */
export const FALLBACK_LLM_MODELS: LlmModelOption[] = [
  { id: "gpt-4o-mini", label: "GPT-4o Mini" },
  { id: "gpt-4o", label: "GPT-4o" },
  { id: "gpt-4-turbo", label: "GPT-4 Turbo" },
  { id: "gpt-4", label: "GPT-4" },
  { id: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
  { id: "o1-mini", label: "o1-mini" },
  { id: "o3-mini", label: "o3-mini" },
];

export const DEFAULT_LLM_MODEL = "gpt-4o-mini";
