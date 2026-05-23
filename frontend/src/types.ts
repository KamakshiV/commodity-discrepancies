export interface DiscrepancyRecord {
  vbeln: string;
  posnr: string;
  category: string;
  vbap_attributes: Record<string, string>;
  cmm_attributes?: Record<string, string> | null;
  mismatched_fields: string[];
  qrf_research?: Record<string, unknown> | null;
  change_history: Record<string, string | undefined>[];
}

export interface AgentInsight {
  agent_name: string;
  vbeln?: string | null;
  posnr?: string | null;
  classification?: string | null;
  likely_cause?: string | null;
  evidence: string[];
  recommended_action?: string | null;
  recommended_owner?: string | null;
}

export interface AnalysisSummary {
  total_commodity_relevant: number;
  missing_count: number;
  mismatch_count: number;
  clean_count: number;
  executive_summary: string;
  root_cause_summary: string;
  recommended_actions: { issue: string; recommended_owner: string; action: string }[];
  scope_filter?: string;
}

export interface LlmModelOption {
  id: string;
  label: string;
}

export interface LlmConfigResponse {
  default_model: string;
  models: LlmModelOption[];
  ai_configured: boolean;
}

export interface ApplicationLogEntry {
  timestamp: string;
  stage: string;
  level: string;
  message: string;
  detail?: string | null;
  duration_ms?: number | null;
  agent_name?: string | null;
  model?: string | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
}

export interface AnalysisResult {
  discrepancies: DiscrepancyRecord[];
  insights: AgentInsight[];
  summary: AnalysisSummary;
  pdf_available: boolean;
  llm_model_used?: string | null;
  ai_analysis_used?: boolean;
  application_logs?: ApplicationLogEntry[];
  ai_total_tokens?: number | null;
  duration_ms?: number | null;
}

export interface HealthResponse {
  status: string;
  data_source: string;
  shared_data_dir: string;
  google_drive_folder_id?: string | null;
  google_drive_configured: boolean;
  tables_loaded: string[];
}

export interface FileUploadStats {
  filename: string;
  table: string;
  loaded: boolean;
  row_count: number;
  column_count: number;
  columns: string[];
  file_size_bytes: number | null;
  source: string;
  resolved_filename?: string | null;
}

export interface FileStatsResponse {
  files: FileUploadStats[];
}

export interface AttributeMapping {
  vbap_field: string;
  cmm_field: string;
  enabled: boolean;
}

export interface CompareFieldsResponse {
  vbap_fields: string[];
  cmm_fields: string[];
  vbap_join_keys: string[];
  cmm_join_keys: string[];
  default_mappings: AttributeMapping[];
}

export type DataInputMode = "vbeln" | "erdat";

export interface AnalysisScope {
  mode: DataInputMode;
  vbelns: string[];
  erdatFrom: string;
  erdatTo: string;
}

export interface ScopePreviewResponse {
  mode: string;
  vbap_loaded: boolean;
  has_erdat_column: boolean;
  commodity_relevant_total: number;
  matching_rows: number;
  matching_orders: number;
  matched_vbelns: string[];
  unknown_vbelns: string[];
  sample_vbelns: string[];
  message: string;
}
