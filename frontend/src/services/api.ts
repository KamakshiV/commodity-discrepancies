import type {
  AnalysisResult,
  AttributeMapping,
  CompareFieldsResponse,
  FileStatsResponse,
  FileUploadStats,
  HealthResponse,
  LlmConfigResponse,
} from "../types";

/** Dev: Vite proxy `/api` → localhost:8000. Prod: set VITE_API_URL or use vercel.json proxy. */
function apiBase(): string {
  const raw = import.meta.env.VITE_API_URL?.trim();
  if (!raw) return "/api";
  return raw.replace(/\/$/, "");
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

export async function runAnalysis(
  useAi: boolean,
  compareMappings: AttributeMapping[],
  llmModel: string,
  generatePdf: boolean = true
): Promise<AnalysisResult> {
  const res = await fetch(`${API}/analyze?use_ai=${useAi}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      use_ai: useAi,
      llm_model: llmModel,
      generate_pdf: generatePdf,
      compare_mappings: compareMappings.filter((m) => m.enabled),
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

export async function clearUploadedFiles(): Promise<{
  message: string;
  deleted: string[];
  file_stats: FileUploadStats[];
}> {
  const res = await fetch(`${API}/data/uploads`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to clear uploads"));
  }
  return res.json();
}

export async function uploadCsvFiles(
  files: File[]
): Promise<{ message: string; file_stats: FileUploadStats[]; tables_loaded: string[] }> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  const res = await fetch(`${API}/data/upload`, { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Upload failed"));
  }
  return res.json();
}

/** @deprecated Use uploadCsvFiles */
export async function uploadCsvFile(file: File) {
  return uploadCsvFiles([file]);
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
