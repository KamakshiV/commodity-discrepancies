import type {
  AnalysisResult,
  AnalysisScope,
  AttributeMapping,
  CompareFieldsResponse,
  FileStatsResponse,
  FileUploadStats,
  HealthResponse,
  LlmConfigResponse,
  ScopePreviewResponse,
} from "../types";

/**
 * Dev: Vite proxy `/api` → localhost:8000.
 * Prod: vercel.json proxy uses `/api`, or set VITE_API_URL to the Render host
 * (with or without `/api` — host-only URLs are normalized automatically).
 */
function apiBase(): string {
  const raw = import.meta.env.VITE_API_URL?.trim();
  if (!raw) return "/api";
  let base = raw.replace(/\/$/, "");
  if (base.startsWith("http") && !base.endsWith("/api")) {
    base = `${base}/api`;
  }
  return base;
}

const API = apiBase();

async function parseErrorDetail(res: Response, fallback: string): Promise<string> {
  const text = await res.text();
  try {
    const err = JSON.parse(text) as { detail?: string | { msg?: string }[] };
    const d = err.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d[0] && typeof d[0] === "object" && "msg" in d[0]) {
      return String(d[0].msg);
    }
  } catch {
    /* not JSON — e.g. Vercel 404 HTML */
  }
  if (text && text.length < 200) return text;
  if (res.status === 404) {
    return `${fallback} (404). Check VITE_API_URL or vercel.json API proxy to the Render backend.`;
  }
  return `${fallback} (HTTP ${res.status})`;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API}/health`);
  if (!res.ok) throw new Error("Health check failed");
  return res.json();
}

export async function fetchLlmConfig(): Promise<LlmConfigResponse> {
  const res = await fetch(`${API}/config/llm`);
  if (!res.ok) throw new Error("Failed to load LLM config");
  return res.json();
}

export async function fetchCompareFields(): Promise<CompareFieldsResponse> {
  const res = await fetch(`${API}/data/compare-fields`);
  if (!res.ok) throw new Error("Failed to load compare fields");
  return res.json();
}

export async function fetchScopePreview(scope: AnalysisScope): Promise<ScopePreviewResponse> {
  const params = new URLSearchParams({ mode: scope.mode });
  if (scope.mode === "vbeln" && scope.vbelns.length) {
    params.set("vbelns", scope.vbelns.join(","));
  }
  if (scope.mode === "erdat") {
    if (scope.erdatFrom) params.set("erdat_from", scope.erdatFrom);
    if (scope.erdatTo) params.set("erdat_to", scope.erdatTo);
  }
  const res = await fetch(`${API}/data/scope-preview?${params}`);
  if (!res.ok) throw new Error("Failed to preview data scope");
  return res.json();
}

export async function runAnalysis(
  useAi: boolean,
  compareMappings: AttributeMapping[],
  llmModel: string,
  generatePdf: boolean = true,
  scope?: AnalysisScope
): Promise<AnalysisResult> {
  const res = await fetch(`${API}/analyze?use_ai=${useAi}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      use_ai: useAi,
      llm_model: llmModel,
      generate_pdf: generatePdf,
      compare_mappings: compareMappings.filter((m) => m.enabled),
      scope_mode: scope?.mode ?? "vbeln",
      scope_vbelns: scope?.mode === "vbeln" ? scope.vbelns : [],
      scope_erdat_from: scope?.mode === "erdat" ? scope.erdatFrom || null : null,
      scope_erdat_to: scope?.mode === "erdat" ? scope.erdatTo || null : null,
    }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Analysis failed"));
  }
  return res.json();
}

export async function fetchFileStats(): Promise<FileStatsResponse> {
  const res = await fetch(`${API}/data/file-stats`);
  if (!res.ok) throw new Error("Failed to load file statistics");
  return res.json();
}

export async function reloadSharedData(): Promise<{
  message: string;
  data_source: string;
  shared_data_dir: string;
  google_drive_folder_id?: string | null;
  google_drive_configured?: boolean;
  tables_loaded: string[];
  file_stats: FileUploadStats[];
}> {
  const res = await fetch(`${API}/data/reload`, { method: "POST" });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to reload shared drive data"));
  }
  return res.json();
}

export async function resetSession(): Promise<{
  message: string;
  shared_data_dir: string;
  tables_loaded: string[];
  file_stats: FileUploadStats[];
}> {
  const res = await fetch(`${API}/session/reset`, { method: "POST" });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to reset session"));
  }
  return res.json();
}

export function pdfDownloadUrl(): string {
  return `${API}/report/pdf`;
}

/** Fetch PDF bytes and trigger browser download. */
export async function downloadPdfReport(filename?: string): Promise<void> {
  const res = await fetch(`${API}/report/pdf`);
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "PDF download failed"));
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || `commodity_discrepancy_report_${new Date().toISOString().slice(0, 10)}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
