import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.schemas import AgentInsight, AnalysisSummary, DiscrepancyCategory, DiscrepancyRecord

# Usable width on letter with 0.75" margins
CONTENT_WIDTH = 6.5 * inch


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
                f"<i>{_escape(vbap_val)}</i>, CMM_VLOGP has <i>{_escape(cmm_val)}</i>."
            )
    return _escape(raw)


def _change_field(ch: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = ch.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
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
    "QRFC_I_QIN_TOP.QUEUE_NAME",
    "QRFC_I_ERR_STATE.UNIT_ID",
    "QRFC_I_ERR_STATE.MESSAGE",
    "QRFC_I_ERR_STATE.MESSAGE_ID",
]

QRFC_RESEARCH_COL_WIDTHS = [
    CONTENT_WIDTH * w for w in (0.14, 0.28, 0.16, 0.24, 0.18)
]


def _qrfc_field(entry: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = entry.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return "—"


def _qrfc_table_rows(d: DiscrepancyRecord) -> List[List[str]]:
    """Flatten qRFC research into PDF table rows for Category 1."""
    research = d.qrf_research or {}
    queues = research.get("queue_matches") or []
    if not queues:
        return [[d.vbeln or "—", "—", "—", "—", "—"]]

    rows: List[List[str]] = []
    for entry in queues:
        err = entry.get("error") if isinstance(entry.get("error"), dict) else {}
        merged = {**err, **entry}
        rows.append([
            d.vbeln or "—",
            _qrfc_field(merged, "queue_name", "QUEUE_NAME"),
            _qrfc_field(merged, "unit_id", "UNIT_ID"),
            _qrfc_field(merged, "message", "MESSAGE"),
            _qrfc_field(merged, "message_id", "MESSAGE_ID"),
        ])
    return rows


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
        self._title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=20,
            spaceAfter=10,
            textColor=colors.HexColor("#1a365d"),
        )
        self._heading_style = ParagraphStyle(
            "Section",
            parent=styles["Heading2"],
            fontSize=12,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor("#2c5282"),
        )
        self._subheading = ParagraphStyle(
            "Sub",
            parent=styles["Heading3"],
            fontSize=10,
            spaceBefore=8,
            spaceAfter=4,
            textColor=colors.HexColor("#2d3748"),
        )
        self._body = styles["BodyText"]
        self._small = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=9, leading=12)
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
            fontSize=8,
            leading=10,
            wordWrap="CJK",
        )
        self._cell_header = ParagraphStyle(
            "CellHeader",
            parent=self._cell,
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
        )

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

        story.append(Paragraph("Commodity Discrepancy Analysis Report", self._title_style))
        story.append(
            Paragraph(
                f"<b>VBAP vs CMM_VLOGP</b> — Generated "
                f"{_escape(datetime.now().strftime('%Y-%m-%d %H:%M'))}",
                self._body,
            )
        )
        analysis_label = (
            f"Analysis: OpenAI ({_escape(llm_model)})"
            if ai_analysis_used and llm_model
            else "Analysis: Rule-based (deterministic engine + SAP research)"
        )
        story.append(Paragraph(analysis_label, self._small))
        story.append(Spacer(1, 0.25 * inch))

        for title, key in [
            ("Executive Summary", "executive_summary"),
            ("What We Found", "what_we_found"),
            ("Why It Matters", "why_it_matters"),
            ("Recommended Actions", "recommended_actions"),
        ]:
            content = narrative.get(key) or (
                summary.executive_summary if key == "executive_summary" else ""
            )
            if content:
                story.append(Paragraph(title, self._heading_style))
                story.append(Paragraph(_escape(str(content)), self._body))
                story.append(Spacer(1, 0.08 * inch))

        story.append(Paragraph("Discrepancy Overview", self._heading_style))
        filter_note = (
            "All VBAP rows in the uploaded file"
            if summary.total_commodity_relevant > 0
            else "No VBAP rows loaded"
        )
        overview_data = [
            ["Metric", "Count"],
            ["VBAP rows analyzed", str(summary.total_commodity_relevant)],
            ["Missing in CMM_VLOGP", str(summary.missing_count)],
            ["Attribute mismatch", str(summary.mismatch_count)],
            ["Aligned (no issue)", str(summary.clean_count)],
        ]
        story.append(self._para_table(overview_data, [3.5 * inch, 3.0 * inch]))
        story.append(Paragraph(filter_note, self._small))
        story.append(Spacer(1, 0.15 * inch))

        missing = [d for d in discrepancies if d.category == DiscrepancyCategory.MISSING_IN_CMM_VLOGP]
        mismatch = [d for d in discrepancies if d.category == DiscrepancyCategory.ATTRIBUTE_MISMATCH]

        story.append(Paragraph("Category 1: Missing in CMM_VLOGP", self._heading_style))
        if not missing:
            story.append(Paragraph("No missing commodity records were identified.", self._body))
        else:
            story.append(
                Paragraph(
                    "These VBAP items are commodity-relevant but have no matching CMM_VLOGP row "
                    "(VBELN ↔ DOCUMENT_CHAR10, POSNR ↔ DOCUMENT_ITEM).",
                    self._small,
                )
            )
            for d in missing:
                story.extend(self._missing_record_block(d))

        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph("Category 2: Attribute Mismatch", self._heading_style))
        if not mismatch:
            story.append(Paragraph("No attribute mismatches were identified.", self._body))
        else:
            story.append(
                Paragraph(
                    "For each order line: mismatched attributes are listed, then CDHDR/CDPOS "
                    "change history (VBEP preferred, VBAP when no VBEP rows exist).",
                    self._small,
                )
            )
            for d in mismatch:
                story.extend(self._mismatch_record_block(d))

        if summary.recommended_actions:
            story.append(PageBreak())
            story.append(Paragraph("Action Plan", self._heading_style))
            act_rows = [["Issue", "Owner", "What to do"]]
            for a in summary.recommended_actions:
                act_rows.append([
                    str(a.get("issue", "")),
                    str(a.get("recommended_owner", "")),
                    str(a.get("action", "")),
                ])
            story.append(self._para_table(act_rows, [2.0 * inch, 1.5 * inch, 3.0 * inch]))

        if insights:
            story.append(Spacer(1, 0.15 * inch))
            story.append(Paragraph("Root-Cause Guidance", self._heading_style))
            ins_rows = [["Sales order", "Source", "Likely cause", "Recommended fix"]]
            for ins in insights[:40]:
                ins_rows.append([
                    f"{ins.vbeln or '—'} / {ins.posnr or '—'}",
                    ins.agent_name.replace("Rule Engine (AI offline)", "Rule-based analysis"),
                    ins.likely_cause or "—",
                    ins.recommended_action or "—",
                ])
            story.append(
                self._para_table(
                    ins_rows,
                    [1.15 * inch, 1.0 * inch, 2.2 * inch, 2.15 * inch],
                )
            )

        story.append(Spacer(1, 0.15 * inch))
        story.append(Paragraph("How to Use This Report", self._heading_style))
        story.append(
            Paragraph(
                "1. Resolve <b>Missing in CMM_VLOGP</b> items first — check qRFC errors and "
                "reprocess failed queues.<br/>"
                "2. For <b>Attribute mismatch</b> items, compare the field values listed and "
                "validate CDPOS change history on VBEP.<br/>"
                "3. Use the Action Plan owners (SAP Basis, Commodity team, Functional analyst) "
                "to route each fix.",
                self._body,
            )
        )

        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()

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

    def _missing_record_block(self, d: DiscrepancyRecord) -> List[Any]:
        blocks: List[Any] = [
            Paragraph(
                f"<b>Sales order {_escape(d.vbeln)} / item {_escape(d.posnr)}</b>",
                self._subheading,
            ),
            Paragraph(
                "No CMM_VLOGP record exists for this VBAP line. Commodity logistics data "
                "was not created or not synchronized.",
                self._small,
            ),
            Paragraph("QRFC RESEARCH", self._detail_label),
        ]
        qrfc_rows: List[List[str]] = [QRFC_RESEARCH_HEADERS]
        qrfc_rows.extend(_qrfc_table_rows(d))
        blocks.append(self._para_table(qrfc_rows, QRFC_RESEARCH_COL_WIDTHS))
        blocks.append(Spacer(1, 0.12 * inch))
        return blocks

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
            for mf in mismatches:
                blocks.append(Paragraph(f"• {_escape(mf)}", self._small))

        if d.change_history:
            blocks.append(
                Paragraph(
                    "CHANGE HISTORY (CDHDR → CDPOS, TABNAME=VBEP)",
                    self._detail_label,
                )
            )
            ch_rows: List[List[str]] = [CHANGE_HISTORY_HEADERS]
            for ch in d.change_history:
                ch_rows.append([
                    _change_field(ch, "CHANGENR", "changenr"),
                    _change_field(ch, "CDPOS_OBJECTID", "OBJECTID", "objectid"),
                    _change_field(ch, "OBJECTCLASS", "objectclass"),
                    _change_field(ch, "TABNAME", "tabname"),
                    _change_field(ch, "FNAME", "fname"),
                    _change_field(ch, "VALUE_OLD", "value_old"),
                    _change_field(ch, "VALUE_NEW", "value_new"),
                ])
            blocks.append(self._para_table(ch_rows, CHANGE_HISTORY_COL_WIDTHS))
        elif mismatches:
            blocks.append(
                Paragraph(
                    "No CDPOS change history found for this order line.",
                    self._small,
                )
            )

        if not mismatches and not d.change_history:
            blocks.append(
                Paragraph("Attribute differences were detected by the rule engine.", self._small)
            )

        blocks.append(Spacer(1, 0.12 * inch))
        return blocks
