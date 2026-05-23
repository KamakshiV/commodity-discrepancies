import shutil
from pathlib import Path

from typing import List, Optional

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
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
)
from app.services.analysis_service import analysis_service
from app.services.app_logger import log_info, log_success
from app.services.data_loader import (
    CMM_JOIN_KEYS,
    DEFAULT_COMPARE_MAPPINGS,
    TABLE_FILES,
    VBAP_JOIN_KEYS,
    all_file_stats,
    build_default_compare_mappings,
    clear_upload_workspace,
    data_store,
    get_compareable_fields,
    resolve_upload_filename,
    stats_for_file,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health():
    data_store.load_all()
    return HealthResponse(
        status="ok",
        data_dir=str(data_store.data_dir),
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
    data_store.load_all()
    defaults = [AttributeMapping(**m) for m in build_default_compare_mappings()]
    return CompareFieldsResponse(
        vbap_fields=get_compareable_fields("VBAP"),
        cmm_fields=get_compareable_fields("CMM_VLOGP"),
        vbap_join_keys=sorted(VBAP_JOIN_KEYS),
        cmm_join_keys=sorted(CMM_JOIN_KEYS),
        default_mappings=defaults,
    )


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
        if body:
            mappings = body.compare_mappings or None
            ai_flag = body.use_ai
            llm_model = body.llm_model
            gen_pdf = body.generate_pdf
        result = analysis_service.run_analysis(
            use_ai=ai_flag,
            compare_mappings=mappings,
            llm_model=llm_model,
            generate_pdf=gen_pdf,
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
    """Per-file row/column statistics for all six SAP table CSVs."""
    data_store.load_all()
    return FileStatsResponse(
        files=[FileUploadStats(**s) for s in all_file_stats()]
    )


@router.post("/data/upload")
async def upload_csv(files: list[UploadFile] = File(...)):
    """Upload one or more SAP table CSVs; merges into persistent upload workspace."""
    allowed = set(TABLE_FILES.values())
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    uploaded: list[str] = []
    file_stats: list[dict] = []

    log_info("api", f"POST /api/data/upload — {len(files)} file(s)")
    try:
        for f in files:
            if not f.filename or not f.filename.lower().endswith(".csv"):
                continue
            name = resolve_upload_filename(f.filename)
            if not name:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Unexpected file '{f.filename}'. "
                        "Name exports to start with the table (e.g. VBAP_*.csv) "
                        f"or use: {sorted(allowed)}"
                    ),
                )
            dest = settings.upload_dir / name
            with dest.open("wb") as out:
                shutil.copyfileobj(f.file, out)
            uploaded.append(name)
            table = next(t for t, fn in TABLE_FILES.items() if fn == name)
            file_stats.append(stats_for_file(table, name))

        if not uploaded:
            raise HTTPException(
                status_code=400,
                detail=f"No valid CSV files. Expected one of: {sorted(allowed)}",
            )

        data_store.load_all()
        log_success(
            "api",
            f"Upload complete — {', '.join(uploaded)}",
            detail=f"tables={data_store.loaded_tables()}",
        )
        return {
            "message": "Data uploaded successfully",
            "files": uploaded,
            "tables_loaded": data_store.loaded_tables(),
            "file_stats": file_stats,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/data/uploads")
def delete_uploads():
    """Delete all uploaded CSV files and clear in-memory analysis data."""
    log_info("api", "DELETE /api/data/uploads — clearing upload workspace")
    try:
        deleted = clear_upload_workspace()
        analysis_service.reset_session()
        log_success(
            "api",
            f"Upload workspace cleared — {len(deleted)} file(s) removed",
            detail=", ".join(deleted) if deleted else "no files on disk",
        )
        return {
            "message": "Uploaded files deleted",
            "deleted": deleted,
            "tables_loaded": data_store.loaded_tables(),
            "file_stats": [stats_for_file(t, fn) for t, fn in TABLE_FILES.items()],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/data/tables")
def list_tables():
    data_store.load_all()
    counts = {table: len(data_store.get(table)) for table in TABLE_FILES}
    return {"data_dir": str(data_store.data_dir), "row_counts": counts}
