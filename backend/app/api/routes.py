from typing import List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response

from app.config import is_openai_configured, settings
from app.models.schemas import (
    AnalysisResult,
    AnalyzeRequest,
    AttributeMapping,
    CompareFieldsResponse,
    FileStatsResponse,
    FileUploadStats,
    HealthResponse,
    LlmConfigResponse,
    LlmModelOption,
    ScopePreviewResponse,
)
from app.services.analysis_service import analysis_service
from app.services.app_logger import log_info, log_success
from app.services.data_loader import (
    CMM_JOIN_KEYS,
    TABLE_FILES,
    VBAP_JOIN_KEYS,
    all_file_stats,
    all_file_stats_from_store,
    build_default_compare_mappings,
    clear_data_cache,
    data_store,
    get_compareable_fields,
    preview_scope,
    stats_for_file,
    sync_data_source,
)
from app.services.google_drive_sync import is_google_drive_configured

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health():
    if not data_store._require_reload and not data_store.has_tables_in_memory():
        data_store.load_all()
    return HealthResponse(
        status="ok",
        data_source=settings.data_source,
        shared_data_dir=str(settings.shared_data_dir),
        google_drive_folder_id=settings.google_drive_folder_id or None,
        google_drive_configured=is_google_drive_configured(),
        tables_loaded=data_store.loaded_tables(),
    )


@router.get("/config/llm", response_model=LlmConfigResponse)
def llm_config():
    """OpenAI model list for UI dropdown and default from .env."""
    models = settings.openai_model_list
    return LlmConfigResponse(
        default_model=settings.openai_model,
        models=[
            LlmModelOption(id=m, label=m.replace("-", " ").title().replace("Gpt", "GPT"))
            for m in models
        ],
        ai_configured=is_openai_configured(),
    )


@router.get("/data/compare-fields", response_model=CompareFieldsResponse)
def compare_fields():
    """List compareable columns from VBAP and CMM_VLOGP CSVs plus default mappings."""
    if not data_store._require_reload and not data_store.has_tables_in_memory():
        data_store.load_all()
    defaults = [AttributeMapping(**m) for m in build_default_compare_mappings()]
    return CompareFieldsResponse(
        vbap_fields=get_compareable_fields("VBAP"),
        cmm_fields=get_compareable_fields("CMM_VLOGP"),
        vbap_join_keys=sorted(VBAP_JOIN_KEYS),
        cmm_join_keys=sorted(CMM_JOIN_KEYS),
        default_mappings=defaults,
    )


@router.get("/data/scope-preview", response_model=ScopePreviewResponse)
def scope_preview(
    mode: str = Query("vbeln", description="vbeln | erdat"),
    vbelns: Optional[str] = Query(None, description="Comma-separated VBELN values"),
    erdat: Optional[str] = Query(None, description="Legacy single ERDAT (YYYYMMDD or ISO date)"),
    erdat_from: Optional[str] = Query(None, description="ERDAT range start (YYYYMMDD or ISO date)"),
    erdat_to: Optional[str] = Query(None, description="ERDAT range end (YYYYMMDD or ISO date)"),
):
    """Preview how many VBAP rows match the selected input scope (shared drive data)."""
    parsed_vbelns = [v.strip() for v in (vbelns or "").split(",") if v.strip()]
    preview = preview_scope(
        data_store.get("VBAP"),
        mode=mode,
        vbelns=parsed_vbelns if mode == "vbeln" else None,
        erdat=erdat if mode == "erdat" else None,
        erdat_from=erdat_from if mode == "erdat" else None,
        erdat_to=erdat_to if mode == "erdat" else None,
    )
    return ScopePreviewResponse(**preview)


@router.post("/data/reload")
def reload_shared_data():
    """Reload SAP CSVs — syncs from Google Drive when DATA_SOURCE=google_drive."""
    log_info(
        "api",
        f"POST /api/data/reload — source={settings.data_source}, cache={settings.shared_data_dir}",
    )
    try:
        sync_info = sync_data_source()
        data_store._require_reload = False
        data_store._tables.clear()
        data_store.load_all(force=True)
        tables = data_store.loaded_tables()
        log_success(
            "api",
            f"Data reload — tables: {', '.join(tables) or 'none'}",
            detail=sync_info.get("message"),
        )
        return {
            "message": sync_info.get("message") or "Data reloaded",
            "data_source": settings.data_source,
            "shared_data_dir": str(settings.shared_data_dir),
            "google_drive_folder_id": settings.google_drive_folder_id or None,
            "google_drive_configured": is_google_drive_configured(),
            "sync": sync_info,
            "tables_loaded": tables,
            "file_stats": [FileUploadStats(**s) for s in all_file_stats_from_store()],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/session/reset")
def reset_session():
    """Clear analysis session, in-memory cache, and Google Drive download cache."""
    log_info("api", "POST /api/session/reset")
    try:
        cache_info = clear_data_cache()
        analysis_service.reset_session()
        return {
            "message": cache_info.get("message", "Session reset"),
            "data_source": settings.data_source,
            "shared_data_dir": str(settings.shared_data_dir),
            "cache": cache_info,
            "tables_loaded": data_store.loaded_tables(),
            "file_stats": [stats_for_file(t, fn) for t, fn in TABLE_FILES.items()],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/analyze", response_model=AnalysisResult)
def analyze(
    use_ai: bool = Query(True, description="Run CrewAI agents (requires OPENAI_API_KEY)"),
    body: Optional[AnalyzeRequest] = Body(None),
):
    log_info("api", "POST /api/analyze received")
    try:
        mappings: Optional[List[AttributeMapping]] = None
        ai_flag = use_ai
        llm_model: Optional[str] = None
        gen_pdf = True
        scope_mode = "vbeln"
        scope_vbelns: Optional[List[str]] = None
        scope_erdat: Optional[str] = None
        scope_erdat_from: Optional[str] = None
        scope_erdat_to: Optional[str] = None
        if body:
            mappings = body.compare_mappings or None
            ai_flag = body.use_ai
            llm_model = body.llm_model
            gen_pdf = body.generate_pdf
            scope_mode = body.scope_mode or "vbeln"
            scope_vbelns = body.scope_vbelns or None
            scope_erdat = body.scope_erdat
            scope_erdat_from = body.scope_erdat_from
            scope_erdat_to = body.scope_erdat_to
        result = analysis_service.run_analysis(
            use_ai=ai_flag,
            compare_mappings=mappings,
            llm_model=llm_model,
            generate_pdf=gen_pdf,
            scope_mode=scope_mode,
            scope_vbelns=scope_vbelns,
            scope_erdat=scope_erdat,
            scope_erdat_from=scope_erdat_from,
            scope_erdat_to=scope_erdat_to,
        )
        log_success(
            "api",
            f"POST /api/analyze completed — {len(result.discrepancies)} discrepancies",
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/analyze", response_model=AnalysisResult)
def analyze_get(use_ai: bool = Query(True)):
    return analyze(use_ai=use_ai, body=None)


@router.get("/report/pdf")
def download_pdf():
    try:
        pdf_bytes = analysis_service.generate_pdf()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=commodity_discrepancy_report.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/data/file-stats", response_model=FileStatsResponse)
def file_stats():
    """Per-file row/column statistics for SAP table CSVs on disk."""
    return FileStatsResponse(
        files=[FileUploadStats(**s) for s in all_file_stats()]
    )


@router.get("/data/tables")
def list_tables():
    data_store.load_all()
    counts = {table: len(data_store.get(table)) for table in TABLE_FILES}
    return {
        "shared_data_dir": str(settings.shared_data_dir),
        "row_counts": counts,
    }
