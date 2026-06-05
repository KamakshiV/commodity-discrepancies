from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DiscrepancyCategory(str, Enum):
    MISSING_IN_CMM_VLOGP = "Missing in CMM_VLOGP"
    ATTRIBUTE_MISMATCH = "Attribute Mismatch"
    NONE = "None"


class DiscrepancyRecord(BaseModel):
    vbeln: str
    posnr: str
    category: DiscrepancyCategory
    trmrisk_relevant: str = "C"
    vbap_attributes: Dict[str, Any] = Field(default_factory=dict)
    cmm_attributes: Optional[Dict[str, Any]] = None
    vbap_line_fields: Dict[str, str] = Field(
        default_factory=dict,
        description="VBAP columns for PDF: MANDT, PRICING_KEY, VERSION, KPOSN, KSCHL",
    )
    mismatched_fields: List[str] = Field(default_factory=list)
    qrf_research: Optional[Dict[str, Any]] = None
    change_history: List[Dict[str, Any]] = Field(default_factory=list)
    cmm_match_path: Optional[str] = Field(
        None,
        description="How VBAP matched CMM_VLOGP: direct (DOCUMENT_CHAR10) or predecessor",
    )


class AgentInsight(BaseModel):
    agent_name: str
    vbeln: Optional[str] = None
    posnr: Optional[str] = None
    classification: Optional[str] = None
    likely_cause: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)
    recommended_action: Optional[str] = None
    recommended_owner: Optional[str] = None
    narrative: Optional[str] = None


class AnalysisSummary(BaseModel):
    total_commodity_relevant: int
    missing_count: int
    mismatch_count: int
    clean_count: int
    executive_summary: str = ""
    root_cause_summary: str = ""
    recommended_actions: List[Dict[str, str]] = Field(default_factory=list)
    scope_filter: str = ""


class ApplicationLogEntry(BaseModel):
    timestamp: str
    stage: str
    level: str
    message: str
    detail: Optional[str] = None
    duration_ms: Optional[float] = None
    agent_name: Optional[str] = None
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class AnalysisResult(BaseModel):
    discrepancies: List[DiscrepancyRecord]
    insights: List[AgentInsight]
    summary: AnalysisSummary
    pdf_available: bool = False
    llm_model_used: Optional[str] = None
    ai_analysis_used: bool = False
    application_logs: List[ApplicationLogEntry] = Field(default_factory=list)
    ai_total_tokens: Optional[int] = None
    duration_ms: Optional[int] = None


class HealthResponse(BaseModel):
    status: str
    data_source: str = "local"
    shared_data_dir: str
    google_drive_folder_id: Optional[str] = None
    google_drive_configured: bool = False
    tables_loaded: List[str]


class FileUploadStats(BaseModel):
    filename: str
    table: str
    loaded: bool
    row_count: int = 0
    column_count: int = 0
    columns: List[str] = Field(default_factory=list)
    file_size_bytes: Optional[int] = None
    source: str = "sample"
    resolved_filename: Optional[str] = None


class FileStatsResponse(BaseModel):
    files: List[FileUploadStats]


class AttributeMapping(BaseModel):
    vbap_field: str
    cmm_field: str
    enabled: bool = True


class CompareFieldsResponse(BaseModel):
    vbap_fields: List[str]
    cmm_fields: List[str]
    vbap_join_keys: List[str] = Field(default_factory=lambda: ["VBELN", "POSNR"])
    cmm_join_keys: List[str] = Field(
        default_factory=lambda: ["DOCUMENT_CHAR10", "DOCUMENT_ITEM"]
    )
    default_mappings: List[AttributeMapping] = Field(default_factory=list)


class LlmModelOption(BaseModel):
    id: str
    label: str


class LlmConfigResponse(BaseModel):
    default_model: str
    models: List[LlmModelOption]
    ai_configured: bool = False


class AnalyzeRequest(BaseModel):
    compare_mappings: List[AttributeMapping] = Field(default_factory=list)
    use_ai: bool = True
    llm_model: Optional[str] = None
    generate_pdf: bool = True
    scope_mode: str = "vbeln"
    scope_vbelns: List[str] = Field(default_factory=list)
    scope_erdat: Optional[str] = None
    scope_erdat_from: Optional[str] = None
    scope_erdat_to: Optional[str] = None


class ScopePreviewResponse(BaseModel):
    mode: str
    vbap_loaded: bool
    has_erdat_column: bool
    commodity_relevant_total: int
    matching_rows: int
    matching_orders: int
    matched_vbelns: List[str] = Field(default_factory=list)
    unknown_vbelns: List[str] = Field(default_factory=list)
    sample_vbelns: List[str] = Field(default_factory=list)
    message: str = ""
