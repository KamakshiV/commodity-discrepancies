import time
from pathlib import Path
from typing import List, Optional

from app.config import is_openai_configured, settings
from app.models.schemas import AnalysisResult, AttributeMapping, DiscrepancyCategory
from app.services.agents.crew_orchestrator import AgentOrchestrator
from app.services.app_logger import (
    StageTimer,
    begin_analysis_logs,
    collect_logs,
    log_info,
    log_success,
    log_warning,
)
from app.services.data_loader import (
    DEFAULT_COMPARE_MAPPINGS,
    build_default_compare_mappings,
    build_scope_label,
    data_store,
)
from app.services.pdf_generator import PDFGenerator
from app.services.rule_engine import RuleEngine

_pdf_cache: Optional[bytes] = None
_last_result: Optional[AnalysisResult] = None
_last_compare_mappings: List[dict] = DEFAULT_COMPARE_MAPPINGS.copy()
_last_llm_model: str = settings.openai_model


def _resolve_model(requested: Optional[str]) -> str:
    if requested and requested.strip():
        return requested.strip()
    return settings.openai_model


class AnalysisService:
    def __init__(self):
        self.orchestrator = AgentOrchestrator()
        self.pdf_gen = PDFGenerator()

    def run_analysis(
        self,
        use_ai: bool = True,
        compare_mappings: Optional[List[AttributeMapping]] = None,
        llm_model: Optional[str] = None,
        generate_pdf: bool = True,
        scope_mode: str = "vbeln",
        scope_vbelns: Optional[List[str]] = None,
        scope_erdat: Optional[str] = None,
        scope_erdat_from: Optional[str] = None,
        scope_erdat_to: Optional[str] = None,
    ) -> AnalysisResult:
        global _last_result, _pdf_cache, _last_compare_mappings, _last_llm_model

        begin_analysis_logs()
        analysis_started = time.perf_counter()
        _last_llm_model = _resolve_model(llm_model)

        scope_label = build_scope_label(
            scope_mode,
            scope_vbelns,
            scope_erdat,
            scope_erdat_from,
            scope_erdat_to,
        )
        log_info(
            "analysis",
            "Analysis run started",
            detail=(
                f"use_ai={use_ai}, model={_last_llm_model}, "
                f"generate_pdf={generate_pdf}, "
                f"openai_configured={is_openai_configured()}, "
                f"scope={scope_label}"
            ),
        )

        with StageTimer("data_load", "Loading SAP table CSVs", "Data load complete"):
            if data_store._require_reload:
                raise ValueError(
                    "Data is not loaded in memory. Reload or sync data from Step 1 before analyzing."
                )
            data_store.load_all()
            tables = data_store.loaded_tables()
            log_info(
                "data_load",
                f"Tables loaded: {', '.join(tables) if tables else 'none'}",
                detail=f"data_dir={data_store.data_dir}",
            )

        if compare_mappings:
            _last_compare_mappings = [m.model_dump() for m in compare_mappings]
            enabled = [m for m in compare_mappings if m.enabled]
            log_info(
                "analysis",
                f"Using {len(enabled)} enabled attribute mapping(s) from request",
                detail=", ".join(f"{m.vbap_field}→{m.cmm_field}" for m in enabled),
            )
        elif not _last_compare_mappings or _last_compare_mappings == DEFAULT_COMPARE_MAPPINGS:
            _last_compare_mappings = build_default_compare_mappings()
            log_info(
                "analysis",
                f"Using {len(_last_compare_mappings)} data-driven default attribute mapping(s)",
            )
        else:
            log_info("analysis", "Using saved attribute mappings from prior run")

        ai_total_tokens = 0

        with StageTimer(
            "rule_engine",
            "Running rule engine (VBAP ↔ CMM_VLOGP join & compare)",
            "Rule engine complete",
        ):
            engine = RuleEngine(
                data_store,
                compare_mappings=_last_compare_mappings,
                scope_vbelns=scope_vbelns if scope_mode == "vbeln" else None,
                scope_erdat=scope_erdat if scope_mode == "erdat" else None,
                scope_erdat_from=scope_erdat_from if scope_mode == "erdat" else None,
                scope_erdat_to=scope_erdat_to if scope_mode == "erdat" else None,
            )
            total = engine.count_commodity_relevant()
            discrepancies = engine.run()
            missing = sum(
                1
                for d in discrepancies
                if d.category == DiscrepancyCategory.MISSING_IN_CMM_VLOGP
            )
            mismatch = len(discrepancies) - missing
            log_info(
                "rule_engine",
                (
                    f"{total} commodity-relevant VBAP row(s); "
                    f"{len(discrepancies)} discrepancy(ies) "
                    f"({missing} missing, {mismatch} mismatch)"
                ),
            )

        ai_analysis_used = False
        if use_ai:
            with StageTimer("ai_agent", "Invoking OpenAI agents", "AI agent stage complete"):
                insights, summary, ai_analysis_used, ai_total_tokens = self.orchestrator.run(
                    discrepancies, total, llm_model=_last_llm_model
                )
        else:
            log_warning("ai_agent", "AI disabled by request — rule-based analysis only")
            insights, summary = self.orchestrator._fallback(
                discrepancies, total, ai_attempted=False
            )

        result = AnalysisResult(
            discrepancies=discrepancies,
            insights=insights,
            summary=summary,
            pdf_available=False,
            llm_model_used=_last_llm_model if ai_analysis_used else None,
            ai_analysis_used=ai_analysis_used,
            ai_total_tokens=ai_total_tokens if ai_total_tokens else None,
        )
        result.summary.scope_filter = scope_label
        _last_result = result
        _pdf_cache = None

        if generate_pdf:
            with StageTimer("pdf", "Generating PDF report", "PDF generation complete"):
                self.generate_pdf()
                result.pdf_available = True
                result.ai_total_tokens = _last_result.ai_total_tokens

        duration_ms = int((time.perf_counter() - analysis_started) * 1000)
        result.duration_ms = duration_ms
        log_success(
            "analysis",
            (
                f"Analysis run finished — {len(discrepancies)} discrepancies, "
                f"ai_used={ai_analysis_used}, duration_ms={duration_ms}"
                + (
                    f", ai_tokens={ai_total_tokens:,}"
                    if ai_total_tokens
                    else ""
                )
            ),
        )
        result.application_logs = collect_logs()
        return result

    def generate_pdf(self) -> bytes:
        global _last_result, _pdf_cache

        if _last_result is None:
            self.run_analysis(generate_pdf=False)

        assert _last_result is not None
        if _pdf_cache is not None:
            log_info("pdf", "Returning cached PDF report")
            return _pdf_cache

        narrative = self.orchestrator.build_pdf_narrative(
            _last_result.summary,
            _last_result.discrepancies,
        )

        with StageTimer("pdf", "Building PDF document", "PDF document built"):
            _pdf_cache = self.pdf_gen.build(
                narrative,
                _last_result.summary,
                _last_result.discrepancies,
                _last_result.insights,
                llm_model=_last_llm_model if _last_result.ai_analysis_used else None,
                ai_analysis_used=_last_result.ai_analysis_used,
            )
        _last_result.pdf_available = True
        return _pdf_cache

    def reload_data(self, data_dir: Path) -> None:
        data_store.reload(data_dir)

    def reset_session(self) -> None:
        """Clear cached analysis result and PDF after Start Over."""
        global _last_result, _pdf_cache
        _last_result = None
        _pdf_cache = None


analysis_service = AnalysisService()
