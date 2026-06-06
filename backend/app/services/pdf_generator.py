import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.schemas import AgentInsight, AnalysisSummary, DiscrepancyCategory, DiscrepancyRecord
from app.services.field_compare import format_display_value
from app.services.finetuning_message_map import resolve_finetuning_from_qrfc_err

# Usable width on letter with 0.75" margins
CONTENT_WIDTH = 6.5 * inch

EXECUTIVE_SUMMARY_LEAD = (
    "During the latest End-of-Day (EOD) portfolio reconciliation, our risk controls "
    "identified systemic alignment anomalies between the physical commercial sales "
    "contracts system (VBAP) and our active Risk Position Ledger (CMM_VLOGP)."
)


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _format_mismatch_line(raw: str) -> str:
    """Turn 'VBAP/CMM: a != b' into plain language."""
    if ":" in raw and "!=" in raw:
        left, rest = raw.split(":", 1)
        if "!=" in rest:
            vbap_val, cmm_val = [p.strip() for p in rest.split("!=", 1)]
            fields = left.strip()
            return (
                f"<b>{_escape(fields)}</b>: VBAP has "
                f"<i>{_escape(format_display_value(vbap_val))}</i>, "
                f"CMM_VLOGP has <i>{_escape(format_display_value(cmm_val))}</i>."
            )
    return _escape(raw)


def _change_field(ch: Dict[str, Any], *keys, format_value: bool = False) -> str:
    for key in keys:
        val = ch.get(key)
        if val is not None and str(val).strip():
            text = str(val).strip()
            return format_display_value(text) if format_value else text
    return "—"


CHANGE_HISTORY_HEADERS = [
    "CHANGENR",
    "OBJECTID",
    "OBJECTCLASS",
    "TABNAME",
    "FNAME",
    "VALUE_OLD",
    "VALUE_NEW",
]

CHANGE_HISTORY_COL_WIDTHS = [
    CONTENT_WIDTH * w for w in (0.13, 0.13, 0.14, 0.11, 0.16, 0.16, 0.17)
]

QRFC_RESEARCH_HEADERS = [
    "VBAP.VBELN",
    "VBAP.POSNR",
    "QRFC_I_QIN_TOP.QUEUE_NAME",
    "QRFC_I_ERR_STATE.UNIT_ID",
    "QRFC_I_ERR_STATE.MESSAGE",
    "QRFC_I_ERR_STATE.MESSAGE_ID",
]

QRFC_RESEARCH_COL_WIDTHS = [
    CONTENT_WIDTH * w for w in (0.12, 0.1, 0.22, 0.14, 0.22, 0.2)
]

CATEGORY1_HEADERS = [
    "S.NO",
    "VBAP.VBELN",
    "VBAP.POSNR",
    "Standard System Text",
    "SAP Component Area",
    "Diagnostic T-Code",
]

CATEGORY1_COL_WIDTHS = [
    CONTENT_WIDTH * w for w in (0.05, 0.12, 0.10, 0.38, 0.18, 0.17)
]

CATEGORY2_DETAIL_HEADERS = [
    "S.NO",
    "VBELN",
    "POSNR",
    "Mismatch attribute",
    "CDPOS.TABNAME",
    "CDPOS.FNAME",
    "CDPOS.VALUE_OLD",
    "CDPOS.VALUE_NEW",
]
CATEGORY2_DETAIL_WIDTHS = [
    CONTENT_WIDTH * w for w in (0.05, 0.11, 0.09, 0.17, 0.10, 0.12, 0.17, 0.19)
]

OWNER_EXEC_LABELS = {
    "SAP Basis": "OPERATIONAL CONTROLS (IT Basis Team)",
    "SAP Commodity Team": "MARKET RISK DESK (Risk Operations)",
    "Functional Analyst": "COMMODITY PORTFOLIO AUDITING (Functional Analyst)",
}


def _format_owner_label(owner: str) -> str:
    """Human-readable owner line for Section 4 action items."""
    text = (owner or "").strip()
    if not text or text.upper() == "TBD":
        return "TBD (Unassigned)"
    return OWNER_EXEC_LABELS.get(text, text)


def _qrfc_field(entry: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = entry.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return "—"


MAX_CHANGE_HISTORY_ROWS = 75


def _category1_finetuning_columns(entry: Dict[str, Any]) -> tuple[str, str, str]:
    """Resolve Standard System Text, SAP Component Area, and Diagnostic T-Code."""
    err = entry.get("error") if isinstance(entry.get("error"), dict) else {}
    merged = {**err, **entry}
    finetuning = merged.get("finetuning") if isinstance(merged.get("finetuning"), dict) else {}

    std_text = (
        merged.get("standard_system_text")
        or finetuning.get("standard_system_text")
        or _qrfc_field(merged, "MESSAGE", "message")
    )
    component = merged.get("sap_component_area") or finetuning.get("sap_component_area") or ""
    tcode = merged.get("diagnostic_tcode") or finetuning.get("diagnostic_tcode") or ""

    if not component or not tcode:
        resolved = resolve_finetuning_from_qrfc_err(merged)
        std_text = std_text or resolved.get("standard_system_text") or ""
        component = component or resolved.get("sap_component_area") or ""
        tcode = tcode or resolved.get("diagnostic_tcode") or ""

    return (
        std_text or "—",
        component or "—",
        tcode or "—",
    )


def _qrfc_table_rows(d: DiscrepancyRecord) -> List[List[str]]:
    """Category 1 rows: VBELN/POSNR + finetuning grid columns per qRFC error."""
    research = d.qrf_research or {}
    queues = research.get("queue_matches") or []
    if not queues:
        return [[
            d.vbeln or "—",
            d.posnr or "—",
            "No qRFC queue match found",
            "—",
            "—",
        ]]

    rows: List[List[str]] = []
    for entry in queues:
        std_text, component, tcode = _category1_finetuning_columns(entry)
        rows.append([
            d.vbeln or "—",
            d.posnr or "—",
            std_text,
            component,
            tcode,
        ])
    return rows


def _build_category1_table_rows(missing: List[DiscrepancyRecord]) -> List[List[str]]:
    """One consolidated table row set: S.NO per missing VBAP line (1..N)."""
    rows: List[List[str]] = []
    for idx, d in enumerate(missing, start=1):
        qrfc_rows = _qrfc_table_rows(d)
        for qrow in qrfc_rows:
            rows.append([str(idx), *qrow])
    return rows


def _qrfc_error_summary(d: DiscrepancyRecord) -> str:
    """Short diagnostic text for summary tables (finetuning grid preferred)."""
    research = d.qrf_research or {}
    queues = research.get("queue_matches") or []
    if not queues:
        return "No qRFC queue match found"
    parts: List[str] = []
    for entry in queues:
        err = entry.get("error") if isinstance(entry.get("error"), dict) else {}
        merged = {**err, **entry}
        std = _qrfc_field(merged, "standard_system_text")
        if std != "—":
            parts.append(std)
            continue
        msg = _qrfc_field(merged, "message", "MESSAGE")
        if msg != "—":
            parts.append(msg)
    return "; ".join(parts) if parts else "—"


def _parse_mismatch_field(raw: str) -> tuple:
    """Parse rule-engine line 'VBAP_F/CMM_F: a != b' into attribute and values."""
    if ":" in raw and "!=" in raw:
        left, rest = raw.split(":", 1)
        vbap_val, cmm_val = [p.strip() for p in rest.split("!=", 1)]
        attr = left.strip()
        if "/" in attr:
            vbap_f, cmm_f = [p.strip() for p in attr.split("/", 1)]
            attr = f"{vbap_f} (VBAP) / {cmm_f} (CMM)"
        return (
            attr,
            format_display_value(vbap_val),
            format_display_value(cmm_val),
        )
    return raw, "—", "—"


def _build_category2_table_rows(mismatch: List[DiscrepancyRecord]) -> List[List[str]]:
    """One row per mismatched attribute × CDPOS change; S.NO increments per table row."""
    rows: List[List[str]] = []
    serial = 1
    for d in mismatch:
        fields = d.mismatched_fields or []
        history = d.change_history or []
        if not fields:
            rows.append([
                str(serial),
                d.vbeln or "—",
                d.posnr or "—",
                "—",
                "—",
                "—",
                "—",
                "—",
            ])
            serial += 1
            continue

        for field_line in fields:
            attr, _, _ = _parse_mismatch_field(field_line)
            if not history:
                rows.append([
                    str(serial),
                    d.vbeln or "—",
                    d.posnr or "—",
                    attr,
                    "—",
                    "—",
                    "—",
                    "—",
                ])
                serial += 1
                continue

            for ch in history:
                rows.append([
                    str(serial),
                    d.vbeln or "—",
                    d.posnr or "—",
                    attr,
                    _change_field(ch, "TABNAME", "tabname"),
                    _change_field(ch, "FNAME", "fname"),
                    _change_field(ch, "VALUE_OLD", "value_old", format_value=True),
                    _change_field(ch, "VALUE_NEW", "value_new", format_value=True),
                ])
                serial += 1
    return rows


def _build_mismatch_summary_rows(mismatch: List[DiscrepancyRecord]) -> List[List[str]]:
    """Backward-compatible alias for Category 2 PDF rows."""
    return _build_category2_table_rows(mismatch)


def count_category2_detail_rows(discrepancies: List[DiscrepancyRecord]) -> int:
    """Rows in Section 2.2 — one per mismatched attribute × CDPOS change (or dash row)."""
    mismatch = [
        d for d in discrepancies
        if d.category == DiscrepancyCategory.ATTRIBUTE_MISMATCH
    ]
    return len(_build_category2_table_rows(mismatch))


def _record_count_footer(count: int, overview_count: int, label: str) -> str:
    tally = (
        f"matches Discrepancy Overview ({overview_count})"
        if count == overview_count
        else f"overview shows {overview_count} — please verify data"
    )
    return f"<b>Total {label}: {count}</b> ({tally})"


def _mismatch_inline_summary(d: DiscrepancyRecord) -> str:
    parts: List[str] = []
    for mf in d.mismatched_fields or []:
        attr, vbap_v, cmm_v = _parse_mismatch_field(mf)
        short = attr.split(" (VBAP)")[0].strip() if " (VBAP)" in attr else attr
        parts.append(f"{short}: VBAP {vbap_v}, CMM {cmm_v}")
    return "; ".join(parts) if parts else "Attribute difference detected"


def _group_recommended_actions(
    insights: List[AgentInsight],
    discrepancies: List[DiscrepancyRecord],
) -> List[tuple]:
    """Return [(action, owner, [(vbeln, posnr), ...]), ...] in stable order."""
    grouped: Dict[tuple, List[tuple]] = {}

    if insights:
        for ins in insights:
            action = (ins.recommended_action or "Review discrepancy").strip()
            owner = (ins.recommended_owner or "TBD").strip()
            key = (action, owner)
            order = (ins.vbeln or "—", ins.posnr or "—")
            if order not in grouped.setdefault(key, []):
                grouped[key].append(order)
    else:
        for d in discrepancies:
            if d.category == DiscrepancyCategory.MISSING_IN_CMM_VLOGP:
                has_qrfc = bool((d.qrf_research or {}).get("queue_matches"))
                key = (
                    ("Reprocess failed qRFC queue", "SAP Basis")
                    if has_qrfc
                    else ("Manual investigation required", "Functional Analyst")
                )
            else:
                key = (
                    "Validate whether CMM_VLOGP should have been updated",
                    "SAP Commodity Team",
                )
            order = (d.vbeln or "—", d.posnr or "—")
            if order not in grouped.setdefault(key, []):
                grouped[key].append(order)

    return [(action, owner, orders) for (action, owner), orders in grouped.items()]


def _alignment_pct(summary: AnalysisSummary) -> float:
    total = summary.total_commodity_relevant or 1
    return (summary.clean_count / total) * 100.0


def _portfolio_status(summary: AnalysisSummary) -> str:
    pct = _alignment_pct(summary)
    if pct >= 99.0:
        return "GREEN"
    if pct >= 90.0:
        return "AMBER"
    return "RED"


def _clean_context(text: str, max_len: int = 120) -> str:
    """Trim SAP diagnostic text for executive bullets."""
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rstrip() + "..."


def _pdf_page_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#718096"))
    page = canvas.getPageNumber()
    canvas.drawCentredString(letter[0] / 2, 0.45 * inch, f"— {page} —")
    canvas.restoreState()


def _format_qrfc_readable(research: Optional[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    if not research:
        return ["No qRFC queue research was found for this order."]
    queues = research.get("queue_matches") or []
    if not queues:
        return ["No matching qRFC queue entry was found in QRFC_I_QIN_TOP."]
    for q in queues:
        qname = q.get("queue_name") or "Unknown queue"
        unit = q.get("unit_id") or "—"
        err = q.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else ""
        mid = err.get("message_id") if isinstance(err, dict) else ""
        line = f"Queue <b>{_escape(str(qname))}</b> (UNIT_ID { _escape(str(unit))})"
        if msg:
            line += f" — Error: {_escape(str(msg))}"
        if mid:
            line += f" [{_escape(str(mid))}]"
        lines.append(line)
    return lines


class PDFGenerator:
    """Builds the commodity discrepancy PDF report (primary deliverable)."""

    def __init__(self):
        styles = getSampleStyleSheet()
        self._report_title = ParagraphStyle(
            "ReportTitle",
            parent=styles["Heading1"],
            fontSize=17,
            leading=20,
            spaceAfter=4,
            textColor=colors.black,
            fontName="Helvetica-Bold",
        )
        self._report_subtitle = ParagraphStyle(
            "ReportSubtitle",
            parent=styles["BodyText"],
            fontSize=11,
            leading=14,
            spaceAfter=2,
            textColor=colors.HexColor("#2d3748"),
        )
        self._report_date = ParagraphStyle(
            "ReportDate",
            parent=styles["BodyText"],
            fontSize=10,
            leading=13,
            spaceAfter=14,
            textColor=colors.HexColor("#4a5568"),
        )
        self._section_heading = ParagraphStyle(
            "SectionHeading",
            parent=styles["Heading2"],
            fontSize=13,
            leading=16,
            spaceBefore=16,
            spaceAfter=8,
            textColor=colors.black,
            fontName="Helvetica-Bold",
        )
        self._subsection_heading = ParagraphStyle(
            "SubsectionHeading",
            parent=styles["Heading3"],
            fontSize=11,
            leading=14,
            spaceBefore=10,
            spaceAfter=6,
            textColor=colors.black,
            fontName="Helvetica-Bold",
        )
        self._body = ParagraphStyle(
            "ExecBody",
            parent=styles["BodyText"],
            fontSize=10,
            leading=14,
            spaceAfter=6,
        )
        self._bullet = ParagraphStyle(
            "ExecBullet",
            parent=self._body,
            leftIndent=14,
            bulletIndent=0,
            spaceAfter=4,
        )
        self._exec_numbered_list = ParagraphStyle(
            "ExecNumberedList",
            parent=self._body,
            leftIndent=16,
            spaceBefore=2,
            spaceAfter=2,
            leading=13,
        )
        self._caption = ParagraphStyle(
            "TableCaption",
            parent=styles["BodyText"],
            fontSize=9,
            leading=12,
            spaceBefore=4,
            spaceAfter=10,
            textColor=colors.HexColor("#4a5568"),
            fontName="Helvetica-Oblique",
        )
        self._small = ParagraphStyle(
            "Small", parent=styles["BodyText"], fontSize=9, leading=12
        )
        self._detail_label = ParagraphStyle(
            "DetailLabel",
            parent=self._small,
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#718096"),
            fontName="Helvetica-Bold",
            spaceBefore=8,
            spaceAfter=4,
        )
        self._cell = ParagraphStyle(
            "Cell",
            parent=styles["BodyText"],
            fontSize=9,
            leading=11,
            wordWrap="CJK",
        )
        self._cell_header = ParagraphStyle(
            "CellHeader",
            parent=self._cell,
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
        )
        # Legacy aliases
        self._title_style = self._report_title
        self._heading_style = self._section_heading
        self._subheading = self._subsection_heading

    def build(
        self,
        narrative: Dict[str, str],
        summary: AnalysisSummary,
        discrepancies: List[DiscrepancyRecord],
        insights: List[AgentInsight],
        llm_model: Optional[str] = None,
        ai_analysis_used: bool = False,
    ) -> bytes:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=0.65 * inch,
            bottomMargin=0.65 * inch,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
        )
        story: List[Any] = []
        generated = datetime.now().strftime("%B %d, %Y")
        missing = [d for d in discrepancies if d.category == DiscrepancyCategory.MISSING_IN_CMM_VLOGP]
        mismatch = [d for d in discrepancies if d.category == DiscrepancyCategory.ATTRIBUTE_MISMATCH]
        total_issues = len(discrepancies)
        align_pct = _alignment_pct(summary)
        status = _portfolio_status(summary)

        # Cover / title block
        story.append(Paragraph("Commodity Exposure &amp; Portfolio Drift Analysis", self._report_title))
        story.append(
            Paragraph(
                "Reconciliation Delta &amp; Technical Validation (VBAP vs. CMM_VLOGP)",
                self._report_subtitle,
            )
        )
        scope_note = summary.scope_filter or "Portfolio scope per analysis run"
        story.append(
            Paragraph(
                f"EOD Close Verification — Generated on {_escape(generated)}<br/>"
                f"<font size='9' color='#718096'>{_escape(scope_note)}</font>",
                self._report_date,
            )
        )

        story.extend(
            self._executive_summary_section(
                narrative, summary, missing, mismatch, total_issues, align_pct, status
            )
        )
        story.extend(
            self._reconciliation_categories_section(summary, missing, mismatch)
        )
        story.extend(
            self._executive_risk_analysis_section(missing, mismatch, insights)
        )
        story.extend(
            self._executive_mitigation_section(summary, insights, discrepancies)
        )

        doc.build(story, onFirstPage=_pdf_page_footer, onLaterPages=_pdf_page_footer)
        buffer.seek(0)
        return buffer.getvalue()

    def _section(self, number: int, title: str) -> Paragraph:
        return Paragraph(f"{number} {_escape(title)}", self._section_heading)

    def _subsection(self, number: str, title: str) -> Paragraph:
        return Paragraph(f"{number} {_escape(title)}", self._subsection_heading)

    def _summary_box(self, flowables: List[Any]) -> Table:
        """Bordered callout for executive summary metrics."""
        if not flowables:
            return Table([[Spacer(1, 0.01 * inch)]], colWidths=[CONTENT_WIDTH])

        rows = [[item] for item in flowables]
        table = Table(rows, colWidths=[CONTENT_WIDTH])
        table.setStyle(
            TableStyle([
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e0")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7fafc")),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ])
        )
        return table

    def _executive_summary_section(
        self,
        narrative: Dict[str, str],
        summary: AnalysisSummary,
        missing: List[DiscrepancyRecord],
        mismatch: List[DiscrepancyRecord],
        total_issues: int,
        align_pct: float,
        status: str,
    ) -> List[Any]:
        blocks: List[Any] = [self._section(1, "Executive Summary")]

        blocks.append(Paragraph(_escape(EXECUTIVE_SUMMARY_LEAD), self._body))

        box_flowables: List[Any] = []
        intro = narrative.get("executive_summary") or summary.executive_summary
        if intro and str(intro).strip() and str(intro).strip() != EXECUTIVE_SUMMARY_LEAD:
            box_flowables.append(Paragraph(_escape(str(intro)), self._body))

        status_color = {
            "GREEN": "#276749",
            "AMBER": "#c05621",
            "RED": "#c53030",
        }.get(status, "#2d3748")
        box_flowables.append(
            Paragraph(
                f"<b>Portfolio Status:</b> "
                f"<font color='{status_color}'><b>{status}</b></font>",
                self._body,
            )
        )

        mismatch_lines = summary.mismatch_detail_count or summary.mismatch_count
        bullets = [
            f"Total Booked Contracts Analyzed: {summary.total_commodity_relevant} Active Sales Orders",
            f"Total Discrepancies Located: {total_issues} Discrepancy Deltas",
            (
                f"Unbooked Exposure Gap (Missing Records): {summary.missing_count} Contracts "
                "(Risk Management Blindspot)"
            ),
            (
                f"Active Portfolio Drift (Attribute Mismatches): {mismatch_lines} Rows "
                "(Physical / Attribute Tracking Drift)"
            ),
            (
                f"Overall Ledger Integrity Index: {align_pct:.2f}% Alignment "
                "(Critical limit is 99.00%)"
            ),
        ]
        numbered = "<br/>".join(
            f"{idx}. {_escape(item)}" for idx, item in enumerate(bullets, start=1)
        )
        box_flowables.append(Paragraph(numbered, self._exec_numbered_list))

        blocks.append(self._summary_box(box_flowables))

        if missing:
            blocks.append(
                Paragraph(
                    "<b>Critical Exposure Delta:</b> "
                    + _escape(
                        f"We detected an exposure gap driven by {summary.missing_count} commercial "
                        "contract line(s) missing from the risk position ledger. Downstream hedging "
                        "systems may be blind to these active market exposures until re-booked."
                    ),
                    self._body,
                )
            )
        if mismatch:
            blocks.append(
                Paragraph(
                    "<b>Operational Portfolio Drift:</b> "
                    + _escape(
                        f"{summary.mismatch_count} active contract line(s) exhibit attribute drift "
                        "between VBAP and CMM_VLOGP. Inventory location or quantity tags may no "
                        "longer reflect the commercial truth, distorting localized risk calculations."
                    ),
                    self._body,
                )
            )

        why = narrative.get("why_it_matters") or summary.root_cause_summary
        if why:
            blocks.append(Spacer(1, 0.06 * inch))
            blocks.append(Paragraph(_escape(str(why)), self._body))

        blocks.append(Spacer(1, 0.08 * inch))
        return blocks

    def _reconciliation_categories_section(
        self,
        summary: AnalysisSummary,
        missing: List[DiscrepancyRecord],
        mismatch: List[DiscrepancyRecord],
    ) -> List[Any]:
        blocks: List[Any] = [
            self._section(2, "Portfolio Reconciliation Detail"),
            Paragraph(
                _escape(
                    f"Of {summary.total_commodity_relevant} commodity-relevant VBAP row(s) in scope, "
                    f"{summary.missing_count} are missing in CMM_VLOGP and "
                    f"{summary.mismatch_count} have attribute differences. "
                    "Every affected order line is listed below."
                ),
                self._body,
            ),
            Spacer(1, 0.1 * inch),
            self._subsection(
                "2.1",
                "Missing Sales Document (VBAP) in Risk Position Ledger (CMM_VLOGP)",
            ),
        ]

        if not missing:
            blocks.append(
                Paragraph("No missing commodity records were identified.", self._body)
            )
        else:
            blocks.append(
                Paragraph(
                    _escape(
                        "These VBAP items are commodity-relevant but have no matching CMM_VLOGP row. "
                        "qRFC errors are mapped to the finetuning diagnostic grid below."
                    ),
                    self._small,
                )
            )
            cat1_rows: List[List[str]] = [CATEGORY1_HEADERS]
            cat1_rows.extend(_build_category1_table_rows(missing))
            blocks.append(self._para_table(cat1_rows, CATEGORY1_COL_WIDTHS))
            blocks.append(
                Paragraph(
                    _record_count_footer(len(missing), summary.missing_count, "missing records"),
                    self._caption,
                )
            )

        blocks.append(Spacer(1, 0.12 * inch))
        blocks.append(self._subsection("2.2", "Category 2 — Attribute Mismatch"))

        if not mismatch:
            blocks.append(
                Paragraph("No attribute mismatches were identified.", self._body)
            )
        else:
            blocks.append(
                Paragraph(
                    _escape(
                        "Each row lists the mismatched attribute for the VBAP line and the "
                        "related CDPOS change fields (TABNAME, FNAME, VALUE_OLD, VALUE_NEW)."
                    ),
                    self._small,
                )
            )
            cat2_rows: List[List[str]] = [CATEGORY2_DETAIL_HEADERS]
            cat2_rows.extend(_build_category2_table_rows(mismatch))
            blocks.append(self._para_table(cat2_rows, CATEGORY2_DETAIL_WIDTHS))
            blocks.append(
                Paragraph(
                    _record_count_footer(
                        len(_build_category2_table_rows(mismatch)),
                        summary.mismatch_detail_count or summary.mismatch_count,
                        "mismatch detail rows",
                    ),
                    self._caption,
                )
            )

        blocks.append(Spacer(1, 0.08 * inch))
        return blocks

    def _executive_risk_analysis_section(
        self,
        missing: List[DiscrepancyRecord],
        mismatch: List[DiscrepancyRecord],
        insights: List[AgentInsight],
    ) -> List[Any]:
        blocks: List[Any] = [self._section(3, "Portfolio Drift & Risk Vector Analysis")]

        if missing:
            blocks.append(self._subsection("3.1", "Systemic Interface Calculation Lags"))
            blocks.append(
                Paragraph(
                    _escape(
                        "Missing ledger entries often trace to stalled commodity interface queues "
                        "during valuation or document creation. Representative diagnostics:"
                    ),
                    self._body,
                )
            )
            shown = 0
            for d in missing:
                research = d.qrf_research or {}
                for entry in research.get("queue_matches") or []:
                    if shown >= 6:
                        break
                    qname = entry.get("queue_name") or "Unknown queue"
                    std = entry.get("standard_system_text") or entry.get("message") or ""
                    line = (
                        f"Order {d.vbeln}/{d.posnr}: {_clean_context(std or qname)} "
                        f"({qname})."
                    )
                    blocks.append(Paragraph(f"– {_escape(line)}", self._bullet))
                    shown += 1
                if shown >= 6:
                    break
            if shown == 0:
                blocks.append(
                    Paragraph(
                        "– No qRFC queue footprint was found; manual reconciliation is advised.",
                        self._bullet,
                    )
                )

        lgort_mismatch = [
            d for d in mismatch
            if any("LGORT" in (f or "").upper() for f in (d.mismatched_fields or []))
        ]
        if lgort_mismatch:
            blocks.append(self._subsection("3.2", "Inventory Location Drift (LGORT Mismatches)"))
            sample_orders = ", ".join(
                f"{d.vbeln}/{d.posnr}" for d in lgort_mismatch[:8]
            )
            blocks.append(
                Paragraph(
                    _escape(
                        f"For order lines including {sample_orders}, change-history and "
                        "attribute comparison indicate storage location drift (e.g. INTR vs FINV)."
                    ),
                    self._body,
                )
            )
            blocks.append(
                Paragraph(
                    "– <b>Impact on risk limits:</b> Risk software may apply transit factors "
                    "where facility storage factors are appropriate, distorting regional allocations.",
                    self._bullet,
                )
            )
            blocks.append(
                Paragraph(
                    "– <b>Operational impact:</b> Custody and jurisdictional profiles may "
                    "register under incorrect storage categories until synchronized.",
                    self._bullet,
                )
            )
        elif mismatch:
            blocks.append(self._subsection("3.2", "Attribute & Quantity Drift"))
            blocks.append(
                Paragraph(
                    _escape(
                        "Attribute mismatches indicate post-booking changes on the commercial "
                        "side that have not propagated to the risk ledger."
                    ),
                    self._body,
                )
            )

        if not missing and not mismatch:
            blocks.append(
                Paragraph("No material drift vectors identified in this run.", self._body)
            )

        blocks.append(Spacer(1, 0.08 * inch))
        return blocks

    def _executive_mitigation_section(
        self,
        summary: AnalysisSummary,
        insights: List[AgentInsight],
        discrepancies: List[DiscrepancyRecord],
    ) -> List[Any]:
        blocks: List[Any] = [
            self._section(4, "Immediate Action & Risk Mitigation Plan"),
            Paragraph("<b>Operational Risk Action Items</b>", self._body),
        ]

        groups = _group_recommended_actions(insights, discrepancies)
        if not groups and summary.recommended_actions:
            for idx, action in enumerate(summary.recommended_actions, start=1):
                owner = _format_owner_label(action.get("recommended_owner", "TBD"))
                blocks.append(
                    Paragraph(
                        f"{idx}. <b>{_escape(owner)}</b>",
                        self._body,
                    )
                )
                blocks.append(
                    Paragraph(
                        f"<b>Action Required:</b> {_escape(action.get('action', ''))}",
                        self._bullet,
                    )
                )
        else:
            for idx, (action, owner, orders) in enumerate(groups, start=1):
                label = _format_owner_label(owner)
                blocks.append(
                    Paragraph(f"{idx}. <b>{_escape(label)}</b>", self._body)
                )
                blocks.append(
                    Paragraph(
                        f"<b>Action Required:</b> {_escape(action)}",
                        self._bullet,
                    )
                )
                target = (
                    f"Resolve {len(orders)} affected order line(s) "
                    "and restore ledger integrity before the next trading session."
                )
                blocks.append(
                    Paragraph(f"<b>Target:</b> {_escape(target)}", self._bullet)
                )
                blocks.append(Spacer(1, 0.04 * inch))

        blocks.append(Spacer(1, 0.12 * inch))
        blocks.append(
            Paragraph(
                "<i>For inquiries or to report remediation milestones, contact the "
                "Commodity Risk Operations desk.</i>",
                self._small,
            )
        )
        return blocks

    def _recommended_actions_blocks(
        self,
        summary: AnalysisSummary,
        insights: List[AgentInsight],
        discrepancies: List[DiscrepancyRecord],
    ) -> List[Any]:
        """Deterministic recommended actions with numbered order lists."""
        groups = _group_recommended_actions(insights, discrepancies)
        blocks: List[Any] = [Paragraph("Recommended Actions", self._heading_style)]

        if not groups:
            blocks.append(
                Paragraph(
                    "No specific actions were generated. Review discrepancies in this report.",
                    self._body,
                )
            )
            blocks.append(Spacer(1, 0.1 * inch))
            return blocks

        for action_idx, (action, owner, orders) in enumerate(groups, start=1):
            blocks.append(
                Paragraph(
                    f"{action_idx}. <b>{_escape(action)}</b> — Owner: {_escape(owner)}",
                    self._body,
                )
            )
            for order_idx, (vbeln, posnr) in enumerate(orders, start=1):
                blocks.append(
                    Paragraph(
                        f"&nbsp;&nbsp;&nbsp;&nbsp;{order_idx}. "
                        f"Order {_escape(vbeln)} / item {_escape(posnr)}",
                        self._small,
                    )
                )
            blocks.append(Spacer(1, 0.06 * inch))

        blocks.append(Spacer(1, 0.04 * inch))
        return blocks

    def _category2_detail_blocks(self, mismatch: List[DiscrepancyRecord]) -> List[Any]:
        """Split Category 2 detail by CDPOS availability to avoid repeated messages."""
        with_history = [d for d in mismatch if d.change_history]
        without_history = [d for d in mismatch if not d.change_history]
        blocks: List[Any] = []

        if with_history:
            blocks.append(
                Paragraph(
                    f"2A — With CDPOS change history ({len(with_history)} order line(s))",
                    self._subheading,
                )
            )
            for d in with_history:
                blocks.extend(self._mismatch_record_block(d))

        if without_history:
            blocks.append(
                Paragraph(
                    f"2B — No CDPOS change history ({len(without_history)} order line(s))",
                    self._subheading,
                )
            )
            blocks.append(
                Paragraph(
                    "These order lines have attribute mismatches but no matching CDPOS "
                    "change documents were found for the sales order.",
                    self._small,
                )
            )
            for idx, d in enumerate(without_history, start=1):
                summary_text = _mismatch_inline_summary(d)
                blocks.append(
                    Paragraph(
                        f"{idx}. Order {_escape(d.vbeln or '—')} / item "
                        f"{_escape(d.posnr or '—')} — {_escape(summary_text)}",
                        self._small,
                    )
                )
            blocks.append(Spacer(1, 0.1 * inch))

        return blocks

    def _para_table(
        self,
        data: List[List[str]],
        col_widths: List[float],
        *,
        layout: str = "header_row",
    ) -> Table:
        wrapped: List[List[Any]] = []
        if layout == "field_value":
            for row in data:
                wrapped.append([
                    Paragraph(_escape(str(row[0])), self._cell_header),
                    Paragraph(_escape(str(row[1]) if len(row) > 1 else ""), self._cell),
                ])
            repeat_rows = 0
        else:
            for row_idx, row in enumerate(data):
                style = self._cell_header if row_idx == 0 else self._cell
                wrapped.append([Paragraph(_escape(str(cell)), style) for cell in row])
            repeat_rows = 1

        table = Table(wrapped, colWidths=col_widths, repeatRows=repeat_rows)
        if layout == "field_value":
            style_commands = [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf2f7")),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
            ]
        else:
            style_commands = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf2f7")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
            ]
        table.setStyle(TableStyle(style_commands))
        return table

    def _mismatch_record_block(self, d: DiscrepancyRecord) -> List[Any]:
        blocks: List[Any] = [
            Paragraph(
                f"<b>Sales order {_escape(d.vbeln)} / item {_escape(d.posnr)}</b>",
                self._subheading,
            ),
        ]
        mismatches = d.mismatched_fields or []

        if mismatches:
            blocks.append(Paragraph("MISMATCHED ATTRIBUTES", self._detail_label))
            for idx, mf in enumerate(mismatches, start=1):
                blocks.append(
                    Paragraph(f"{idx}. {_format_mismatch_line(mf)}", self._small)
                )

        if d.change_history:
            blocks.append(
                Paragraph(
                    "CHANGE HISTORY (CDHDR → CDPOS)",
                    self._detail_label,
                )
            )
            ch_rows: List[List[str]] = [CHANGE_HISTORY_HEADERS]
            history = d.change_history or []
            truncated = len(history) > MAX_CHANGE_HISTORY_ROWS
            for ch in history[:MAX_CHANGE_HISTORY_ROWS]:
                ch_rows.append([
                    _change_field(ch, "CHANGENR", "changenr"),
                    _change_field(ch, "CDPOS_OBJECTID", "OBJECTID", "objectid"),
                    _change_field(ch, "OBJECTCLASS", "objectclass"),
                    _change_field(ch, "TABNAME", "tabname"),
                    _change_field(ch, "FNAME", "fname"),
                    _change_field(ch, "VALUE_OLD", "value_old", format_value=True),
                    _change_field(ch, "VALUE_NEW", "value_new", format_value=True),
                ])
            blocks.append(self._para_table(ch_rows, CHANGE_HISTORY_COL_WIDTHS))
            if truncated:
                blocks.append(
                    Paragraph(
                        _escape(
                            f"Showing first {MAX_CHANGE_HISTORY_ROWS} of "
                            f"{len(history)} change row(s)."
                        ),
                        self._small,
                    )
                )
        elif not mismatches:
            blocks.append(
                Paragraph("Attribute differences were detected by the rule engine.", self._small)
            )

        blocks.append(Spacer(1, 0.12 * inch))
        return blocks
