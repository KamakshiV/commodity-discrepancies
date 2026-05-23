"""
AI agent orchestration using OpenAI Chat Completions (Python 3.9+ compatible).
CrewAI is not required — avoids Python 3.10-only type syntax in older crewai wheels.
"""
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import is_openai_configured, settings
from app.models.schemas import (
    AgentInsight,
    AnalysisSummary,
    DiscrepancyCategory,
    DiscrepancyRecord,
)
from app.services.app_logger import (
    log_ai_agent_finish,
    log_ai_agent_start,
    log_error,
    log_info,
    log_success,
    log_warning,
)


def _chat(
    model: Optional[str],
    system: str,
    user: str,
    agent_name: str,
) -> Tuple[str, Dict[str, Optional[int]]]:
    from openai import OpenAI

    model_id = model or settings.openai_model
    log_ai_agent_start(
        agent_name,
        model_id,
        system_prompt_chars=len(system),
        user_prompt_chars=len(user),
    )

    start = time.perf_counter()
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    content = response.choices[0].message.content or ""
    usage = response.usage
    prompt_tokens = usage.prompt_tokens if usage else None
    completion_tokens = usage.completion_tokens if usage else None
    total_tokens = usage.total_tokens if usage else None

    log_ai_agent_finish(
        agent_name,
        model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        duration_ms=elapsed_ms,
        response_chars=len(content),
    )
    return content, {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _sum_tokens(usages: List[Dict[str, Optional[int]]]) -> int:
    return sum(u.get("total_tokens") or 0 for u in usages)


def _discrepancy_context(records: List[DiscrepancyRecord]) -> str:
    payload = [r.model_dump() for r in records]
    return json.dumps(payload, indent=2, default=str)


class AgentOrchestrator:
    """Runs sequential AI analysis steps on top of deterministic rule-engine output."""

    def __init__(self):
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)

    def run(
        self,
        discrepancies: List[DiscrepancyRecord],
        total_commodity: int,
        llm_model: Optional[str] = None,
    ) -> Tuple[List[AgentInsight], AnalysisSummary, bool, int]:
        """Returns insights, summary, whether live OpenAI was used, and total tokens."""
        model_id = llm_model or settings.openai_model

        if not is_openai_configured():
            log_warning(
                "ai_agent",
                "OpenAI not configured — using rule-based fallback",
                detail="Set OPENAI_API_KEY in backend/.env to enable AI agents",
            )
            ins, summ = self._fallback(discrepancies, total_commodity, ai_attempted=False)
            return ins, summ, False, 0

        try:
            from openai import OpenAI  # noqa: F401
        except ImportError:
            log_warning(
                "ai_agent",
                "openai package not installed — using rule-based fallback",
            )
            ins, summ = self._fallback(discrepancies, total_commodity, ai_attempted=False)
            return ins, summ, False, 0

        context = _discrepancy_context(discrepancies)
        missing = [
            d for d in discrepancies
            if d.category == DiscrepancyCategory.MISSING_IN_CMM_VLOGP
        ]
        mismatch = [
            d for d in discrepancies
            if d.category == DiscrepancyCategory.ATTRIBUTE_MISMATCH
        ]

        log_info(
            "ai_agent",
            (
                f"Starting AI orchestration with model {model_id}: "
                f"{len(discrepancies)} discrepancies "
                f"({len(missing)} missing, {len(mismatch)} mismatch)"
            ),
        )

        token_usages: List[Dict[str, Optional[int]]] = []

        try:
            classify_raw, usage = _chat(
                llm_model,
                "You are a SAP commodity discrepancy classifier. "
                "Never override rule-engine findings. Respond with valid JSON only.",
                (
                    "Classify each discrepancy. Return a JSON array with objects containing: "
                    "vbeln, posnr, classification, likely_cause, evidence (array), recommended_action.\n"
                    f"Data:\n{context}"
                ),
                "Discrepancy Classifier",
            )
            token_usages.append(usage)

            qrfc_raw = ""
            if missing:
                qrfc_raw, usage = _chat(
                    llm_model,
                    "You are a SAP qRFC investigator for missing CMM_VLOGP records. JSON only.",
                    (
                        "Analyze qRFC evidence for missing records. Return JSON array with: "
                        "vbeln, posnr, likely_cause, evidence, recommended_action, recommended_owner.\n"
                        f"Records:\n{json.dumps([m.model_dump() for m in missing], default=str)}"
                    ),
                    "qRFC Investigator",
                )
                token_usages.append(usage)
            else:
                log_info("ai_agent", "Skipping qRFC Investigator — no missing CMM_VLOGP records")

            change_raw = ""
            if mismatch:
                change_raw, usage = _chat(
                    llm_model,
                    "You are a SAP change-document investigator for attribute mismatches. JSON only.",
                    (
                        "Analyze CDHDR/CDPOS change history. Return JSON array with: "
                        "vbeln, posnr, likely_cause, evidence, recommended_action, recommended_owner.\n"
                        f"Records:\n{json.dumps([m.model_dump() for m in mismatch], default=str)}"
                    ),
                    "Change History Investigator",
                )
                token_usages.append(usage)
            else:
                log_info(
                    "ai_agent",
                    "Skipping Change History Investigator — no attribute mismatches",
                )

            summary_raw, usage = _chat(
                llm_model,
                "You are a senior SAP commodity business analyst. JSON only.",
                (
                    f"Summarize {total_commodity} commodity-relevant VBAP rows and "
                    f"{len(discrepancies)} discrepancies ({len(missing)} missing, {len(mismatch)} mismatch). "
                    "Return JSON with: executive_summary, root_cause_summary, "
                    "recommended_actions (array of issue, recommended_owner, action).\n"
                    f"Classifications:\n{classify_raw}\n"
                    f"qRFC:\n{qrfc_raw}\n"
                    f"Changes:\n{change_raw}"
                ),
                "Business Analyst",
            )
            token_usages.append(usage)

            action_raw, usage = _chat(
                llm_model,
                "You are an SAP support lead creating action items. JSON only.",
                (
                    "Return JSON array of action items: issue, recommended_owner, action. "
                    f"Context:\n{summary_raw}"
                ),
                "Action Planner",
            )
            token_usages.append(usage)

            total_tokens = _sum_tokens(token_usages)
            log_success(
                "ai_agent",
                (
                    f"AI orchestration complete — {len(token_usages)} agent call(s), "
                    f"{total_tokens:,} total tokens"
                ),
                detail=f"model={model_id}",
            )

            insights = self._parse_insights_from_raw(
                [
                    (classify_raw, "Discrepancy Classifier"),
                    (qrfc_raw, "qRFC Investigator"),
                    (change_raw, "Change History Investigator"),
                ]
            )
            summary = self._parse_summary_from_raw(
                summary_raw, action_raw, total_commodity, discrepancies
            )
            return insights, summary, True, total_tokens
        except Exception as exc:
            log_error(
                "ai_agent",
                f"OpenAI orchestration failed — falling back to rule-based analysis: {exc}",
                exc=exc,
            )
            ins, summ = self._fallback(discrepancies, total_commodity, ai_attempted=True)
            return ins, summ, False, _sum_tokens(token_usages)

    def _parse_insights_from_raw(
        self, raw_by_agent: List[Tuple[str, str]]
    ) -> List[AgentInsight]:
        insights: List[AgentInsight] = []
        for raw, name in raw_by_agent:
            if not raw:
                continue
            for item in self._safe_json_list(raw):
                if not isinstance(item, dict):
                    continue
                insights.append(
                    AgentInsight(
                        agent_name=name,
                        vbeln=item.get("vbeln"),
                        posnr=item.get("posnr"),
                        classification=item.get("classification"),
                        likely_cause=item.get("likely_cause"),
                        evidence=item.get("evidence") or [],
                        recommended_action=item.get("recommended_action"),
                        recommended_owner=item.get("recommended_owner"),
                    )
                )
        return insights

    def _parse_summary_from_raw(
        self,
        summary_raw: str,
        action_raw: str,
        total_commodity: int,
        discrepancies: List[DiscrepancyRecord],
    ) -> AnalysisSummary:
        missing = sum(
            1 for d in discrepancies
            if d.category == DiscrepancyCategory.MISSING_IN_CMM_VLOGP
        )
        mismatch = sum(
            1 for d in discrepancies
            if d.category == DiscrepancyCategory.ATTRIBUTE_MISMATCH
        )

        summary_data = self._safe_json_dict(summary_raw)
        actions_raw = self._safe_json_list(action_raw)
        actions = summary_data.get("recommended_actions") or actions_raw
        if isinstance(actions, list):
            actions = [a for a in actions if isinstance(a, dict)]
        else:
            actions = []

        return AnalysisSummary(
            total_commodity_relevant=total_commodity,
            missing_count=missing,
            mismatch_count=mismatch,
            clean_count=max(0, total_commodity - len(discrepancies)),
            executive_summary=summary_data.get("executive_summary", ""),
            root_cause_summary=summary_data.get("root_cause_summary", ""),
            recommended_actions=actions,
        )

    def _safe_json_list(self, text: str) -> list:
        try:
            data = json.loads(self._extract_json(text))
            return data if isinstance(data, list) else [data]
        except (json.JSONDecodeError, TypeError):
            return []

    def _safe_json_dict(self, text: str) -> Dict:
        try:
            data = json.loads(self._extract_json(text))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def _extract_json(self, text: str) -> str:
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("[") or part.startswith("{"):
                    return part
        return text

    def _build_root_cause_summary(
        self,
        missing: int,
        mismatch: int,
        total: int,
        *,
        ai_attempted: bool,
    ) -> str:
        parts: List[str] = []
        if missing:
            parts.append(
                f"{missing} sales order item(s) are missing a matching CMM_VLOGP record."
            )
        if mismatch:
            parts.append(
                f"{mismatch} item(s) have attribute differences between VBAP and CMM_VLOGP."
            )
        if not missing and not mismatch:
            parts.append(
                f"All {total} analyzed VBAP row(s) are aligned with CMM_VLOGP for the mapped fields."
            )
        body = " ".join(parts)
        if ai_attempted:
            return (
                body
                + " OpenAI could not complete analysis; rule-based guidance is shown in Insights."
            )
        if is_openai_configured():
            return body
        return (
            body
            + " Add a valid OPENAI_API_KEY in backend/.env to enable AI-generated narratives."
        )

    def _fallback(
        self,
        discrepancies: List[DiscrepancyRecord],
        total_commodity: int,
        *,
        ai_attempted: bool = False,
    ) -> Tuple[List[AgentInsight], AnalysisSummary]:
        log_info(
            "ai_agent",
            f"Running rule-based fallback for {len(discrepancies)} discrepancy record(s)",
        )
        insights: List[AgentInsight] = []
        missing = 0
        mismatch = 0

        for d in discrepancies:
            if d.category == DiscrepancyCategory.MISSING_IN_CMM_VLOGP:
                missing += 1
                has_qrfc = bool(d.qrf_research and d.qrf_research.get("queue_matches"))
                insights.append(
                    AgentInsight(
                        agent_name="Rule-based analysis",
                        vbeln=d.vbeln,
                        posnr=d.posnr,
                        classification="Missing in CMM_VLOGP",
                        likely_cause=(
                            "qRFC queue failure during commodity document creation"
                            if has_qrfc
                            else "No root cause found — manual investigation required"
                        ),
                        evidence=[
                            str(m) for m in (d.qrf_research or {}).get("queue_matches", [])
                        ],
                        recommended_action=(
                            "Reprocess qRFC queue" if has_qrfc else "Manual investigation"
                        ),
                        recommended_owner="SAP Basis" if has_qrfc else "Functional Analyst",
                    )
                )
            elif d.category == DiscrepancyCategory.ATTRIBUTE_MISMATCH:
                mismatch += 1
                insights.append(
                    AgentInsight(
                        agent_name="Rule-based analysis",
                        vbeln=d.vbeln,
                        posnr=d.posnr,
                        classification="Attribute Mismatch",
                        likely_cause=(
                            "Sales order schedule line changed after commodity version was created"
                        ),
                        evidence=d.mismatched_fields + [str(c) for c in d.change_history],
                        recommended_action="Validate whether CMM_VLOGP should have been updated",
                        recommended_owner="SAP Commodity Team",
                    )
                )

        summary = AnalysisSummary(
            total_commodity_relevant=total_commodity,
            missing_count=missing,
            mismatch_count=mismatch,
            clean_count=max(0, total_commodity - len(discrepancies)),
            executive_summary=(
                f"{len(discrepancies)} discrepancies found across {total_commodity} "
                "commodity-relevant sales order items."
            ),
            root_cause_summary=self._build_root_cause_summary(
                missing, mismatch, total_commodity, ai_attempted=ai_attempted
            ),
            recommended_actions=[
                {
                    "issue": "qRFC error found",
                    "recommended_owner": "SAP Basis",
                    "action": "Reprocess failed queue",
                },
                {
                    "issue": "Attribute mismatch",
                    "recommended_owner": "SAP Commodity Team",
                    "action": "Validate update logic",
                },
                {
                    "issue": "No evidence found",
                    "recommended_owner": "Functional Analyst",
                    "action": "Review business process",
                },
            ],
        )
        log_success(
            "ai_agent",
            f"Rule-based fallback complete — {len(insights)} insight(s) generated",
        )
        return insights, summary

    def generate_pdf_narrative(
        self,
        discrepancies: List[DiscrepancyRecord],
        summary: AnalysisSummary,
        insights: List[AgentInsight],
        llm_model: Optional[str] = None,
    ) -> Tuple[Dict[str, str], int]:
        if not is_openai_configured():
            log_info("pdf", "Using template PDF narrative — OpenAI not configured")
            return self._fallback_narrative(summary, discrepancies), 0

        try:
            summary_text = self._plain_summary_for_prompt(summary, discrepancies, insights)
            raw, usage = _chat(
                llm_model,
                "You are a SAP commodity operations report writer. Write clear plain English for business users. "
                "Do not use JSON. Use short paragraphs and bullet lines.",
                (
                    "Write four sections separated by blank lines, with these exact headings on their own line:\n"
                    "EXECUTIVE SUMMARY\n"
                    "WHAT WE FOUND\n"
                    "WHY IT MATTERS\n"
                    "RECOMMENDED ACTIONS\n\n"
                    f"Context:\n{summary_text}"
                ),
                "PDF Narrative Writer",
            )
            parsed = self._parse_narrative_sections(raw)
            tokens = usage.get("total_tokens") or 0
            if parsed:
                log_success("pdf", "AI-generated PDF narrative ready", detail=f"tokens={tokens}")
                return parsed, tokens
            log_warning("pdf", "AI narrative parse failed — using template fallback")
            return self._fallback_narrative(summary, discrepancies), tokens
        except Exception as exc:
            log_error("pdf", f"PDF narrative AI call failed — using template: {exc}", exc=exc)
            return self._fallback_narrative(summary, discrepancies), 0

    def _plain_summary_for_prompt(
        self,
        summary: AnalysisSummary,
        discrepancies: List[DiscrepancyRecord],
        insights: List[AgentInsight],
    ) -> str:
        lines = [
            f"VBAP rows analyzed: {summary.total_commodity_relevant}",
            f"Missing in CMM_VLOGP: {summary.missing_count}",
            f"Attribute mismatches: {summary.mismatch_count}",
        ]
        for d in discrepancies[:15]:
            if d.category == DiscrepancyCategory.MISSING_IN_CMM_VLOGP:
                lines.append(f"Missing: order {d.vbeln} item {d.posnr}")
            else:
                fields = "; ".join(d.mismatched_fields[:3]) if d.mismatched_fields else "see report"
                lines.append(f"Mismatch: order {d.vbeln} item {d.posnr} — {fields}")
        for ins in insights[:10]:
            lines.append(
                f"Guidance for {ins.vbeln}/{ins.posnr}: {ins.likely_cause or ''} — "
                f"Action: {ins.recommended_action or ''}"
            )
        return "\n".join(lines)

    def _parse_narrative_sections(self, text: str) -> Dict[str, str]:
        keys = {
            "EXECUTIVE SUMMARY": "executive_summary",
            "WHAT WE FOUND": "what_we_found",
            "WHY IT MATTERS": "why_it_matters",
            "RECOMMENDED ACTIONS": "recommended_actions",
        }
        result: Dict[str, str] = {}
        current_key: Optional[str] = None
        buffer: List[str] = []
        for line in text.splitlines():
            upper = line.strip().upper()
            if upper in keys:
                if current_key and buffer:
                    result[current_key] = "\n".join(buffer).strip()
                current_key = keys[upper]
                buffer = []
            elif current_key:
                buffer.append(line)
        if current_key and buffer:
            result[current_key] = "\n".join(buffer).strip()
        return result if result else {}

    def _fallback_narrative(
        self,
        summary: AnalysisSummary,
        discrepancies: List[DiscrepancyRecord],
    ) -> Dict[str, str]:
        missing_n = sum(
            1 for d in discrepancies if d.category == DiscrepancyCategory.MISSING_IN_CMM_VLOGP
        )
        mismatch_n = sum(
            1 for d in discrepancies if d.category == DiscrepancyCategory.ATTRIBUTE_MISMATCH
        )
        found_lines = [
            f"Analyzed {summary.total_commodity_relevant} VBAP row(s).",
            f"{missing_n} record(s) are missing in CMM_VLOGP.",
            f"{mismatch_n} record(s) have attribute mismatches.",
        ]
        for d in discrepancies[:20]:
            if d.category == DiscrepancyCategory.MISSING_IN_CMM_VLOGP:
                found_lines.append(
                    f"• Order {d.vbeln} / item {d.posnr}: no CMM_VLOGP match — check qRFC queues."
                )
            else:
                detail = (
                    "; ".join(d.mismatched_fields[:4])
                    if d.mismatched_fields
                    else "mapped fields differ"
                )
                found_lines.append(
                    f"• Order {d.vbeln} / item {d.posnr}: {detail}"
                )
        action_lines = [
            f"• {a.get('issue', 'Issue')}: {a.get('action', '')} "
            f"(Owner: {a.get('recommended_owner', 'TBD')})"
            for a in summary.recommended_actions
        ] or ["• Review each discrepancy in the Root-Cause Guidance section."]
        return {
            "executive_summary": summary.executive_summary
            or (
                f"This report covers {summary.total_commodity_relevant} VBAP lines. "
                f"{len(discrepancies)} issue(s) need attention."
            ),
            "what_we_found": "\n".join(found_lines),
            "why_it_matters": (
                "Commodity-relevant sales orders must stay synchronized with CMM_VLOGP "
                "for logistics, risk reporting, and downstream commodity processes. "
                "Missing or mismatched data can block shipments and distort exposure."
            ),
            "recommended_actions": "\n".join(action_lines),
        }
