import type {
  AnalysisResult,
  AttributeMapping,
  CompareFieldsResponse,
  FileStatsResponse,
  FileUploadStats,
  HealthResponse,
  LlmConfigResponse,
} from "../types";

const API = "/api";

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
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || "Analysis failed");
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
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || "Failed to clear uploads");
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
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || "Upload failed");
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
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || "PDF download failed");
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
