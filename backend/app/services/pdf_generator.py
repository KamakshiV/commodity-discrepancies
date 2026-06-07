import io
from datetime import datetime
from typing import Any, Dict, List, NamedTuple, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.schemas import AgentInsight, AnalysisSummary, DiscrepancyCategory, DiscrepancyRecord
from app.services.field_compare import format_display_value
from app.services.finetuning_message_map import resolve_finetuning_from_qrfc_err
from app.services.pdf_fonts import NOTO_BOLD, NOTO_ITALIC, NOTO_REGULAR, register_pdf_fonts

# Sample PDF margins (~56.7 pt / 0.787 in each side)
PDF_MARGIN = 0.787 * inch
CONTENT_WIDTH = letter[0] - 2 * PDF_MARGIN

# Typography matched to Risk Analysis Report.pdf (Noto Sans, pt sizes from extract)
PDF_TYPE = {
    "title": 17,
    "subtitle": 14,
    "date": 10,
    "section": 14,
    "subsection": 12,
    "body": 11,
    "table": 8,
    "caption": 9,
}

# Visual theme (presentation only — does not affect report logic)
PDF_THEME = {
    "navy": "#1e3a5f",
    "navy_light": "#2c5282",
    "slate": "#4a5568",
    "slate_light": "#718096",
    "border": "#cbd5e0",
    "border_light": "#e2e8f0",
    "surface": "#f7fafc",
    "surface_alt": "#edf2f7",
    "white": "#ffffff",
    "green": "#276749",
    "amber": "#c05621",
    "red": "#c53030",
    "cat1_accent": "#2b6cb0",
    "cat2_accent": "#805ad5",
    "action_orange": "#e68a00",
}

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
    "#",
    "VBELN",
    "POSNR",
    "Attribute",
    "Tabname",
    "Field",
    "Old value",
    "New value",
]
CATEGORY2_DETAIL_WIDTHS = [
    CONTENT_WIDTH * w for w in (0.05, 0.10, 0.07, 0.10, 0.09, 0.10, 0.18, 0.31)
]

# Columns in Category 2 detail rows that must not wrap (#, VBELN, POSNR, Tabname, Field).
CATEGORY2_NOWRAP_COLS = frozenset({0, 1, 2, 4, 5})

OWNER_EXEC_LABELS = {
    "SAP Basis": "OPERATIONAL CONTROLS (IT Basis Team)",
    "SAP Commodity Team": "MARKET RISK DESK (Risk Operations)",
    "Functional Analyst": "COMMODITY PORTFOLIO AUDITING (Functional Analyst)",
}

OWNER_ACTION_TARGETS = {
    "SAP Basis": (
        "Clear interface lags to recover immediate visibility of the "
        "Net Open Position (NOP)."
    ),
    "SAP Commodity Team": (
        "Resolve localized VaR limit calculations before the next trading session."
    ),
    "Functional Analyst": (
        "Trace transaction life cycles to eliminate silent pipeline dropouts."
    ),
}


class OperationalActionItem(NamedTuple):
    """Structured remediation item for Section 4 — owner, issue, steps, scope, target."""

    owner_key: str
    owner_label: str
    issue: str
    steps: List[str]
    affected: str
    target: str


def _format_owner_label(owner: str) -> str:
    """Human-readable owner line for Section 4 action items."""
    text = (owner or "").strip()
    if not text or text.upper() == "TBD":
        return "TBD (Unassigned)"
    return OWNER_EXEC_LABELS.get(text, text)


def _target_for_owner(owner: str, order_count: int) -> str:
    """Default target line keyed to responsible team (matches report mockup)."""
    key = (owner or "").strip()
    if key in OWNER_ACTION_TARGETS:
        return OWNER_ACTION_TARGETS[key]
    if order_count:
        return (
            f"Resolve {order_count} affected order line(s) and restore ledger integrity "
            "before the next trading session."
        )
    return "Restore ledger integrity before the next trading session."


def _order_key(d: DiscrepancyRecord) -> tuple[str, str]:
    return (d.vbeln or "—", d.posnr or "—")


def _sort_discrepancies(records: List[DiscrepancyRecord]) -> List[DiscrepancyRecord]:
    """Stable ordering for all PDF sections (VBELN, POSNR, category)."""
    return sorted(
        records,
        key=lambda d: (_order_key(d)[0], _order_key(d)[1], d.category.value),
    )


def _sorted_unique_orders(records: List[DiscrepancyRecord]) -> List[tuple[str, str]]:
    return sorted({_order_key(d) for d in records})


def _affected_orders_text(
    orders: List[tuple[str, str]],
    *,
    section_ref: str,
    max_show: int = 4,
) -> str:
    if not orders:
        return "None identified in this run."
    shown = orders[:max_show]
    text = ", ".join(f"{vbeln}/{posnr}" for vbeln, posnr in shown)
    remaining = len(orders) - len(shown)
    if remaining > 0:
        return f"{text} (+{remaining} more — see {section_ref})"
    return f"{text} (full list in {section_ref})"


def _unique_qrfc_diagnostics(
    records: List[DiscrepancyRecord],
) -> List[tuple[str, str]]:
    """Return deduplicated (standard_system_text, diagnostic_tcode) pairs — sorted."""
    seen: set[tuple[str, str]] = set()
    out: List[tuple[str, str]] = []
    for d in _sort_discrepancies(records):
        entries = (d.qrf_research or {}).get("queue_matches") or []
        for entry in sorted(
            entries,
            key=lambda e: (
                str(e.get("standard_system_text") or e.get("message") or ""),
                str(e.get("queue_name") or ""),
            ),
        ):
            std_text, _, tcode = _category1_finetuning_columns(entry)
            if std_text == "—" and tcode == "—":
                continue
            key = (std_text, tcode)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return sorted(out, key=lambda pair: (pair[0].lower(), pair[1].lower()))


def _unique_mismatch_attributes(records: List[DiscrepancyRecord]) -> List[str]:
    attrs: set[str] = set()
    for d in _sort_discrepancies(records):
        for raw in sorted(d.mismatched_fields or []):
            attr, _, _ = _parse_mismatch_field(raw)
            short = attr.split(" (VBAP)")[0].strip() if " (VBAP)" in attr else attr
            if short:
                attrs.add(short)
    return sorted(attrs, key=str.lower)


def _build_operational_action_items(
    discrepancies: List[DiscrepancyRecord],
) -> List[OperationalActionItem]:
    """
    Build deterministic, step-by-step action items from reconciliation findings.

    Rule-based only — never reads AI insights or summary.recommended_actions.
    Same discrepancy data always produces identical Section 4 content.
    """
    ordered = _sort_discrepancies(discrepancies)
    missing = [
        d for d in ordered
        if d.category == DiscrepancyCategory.MISSING_IN_CMM_VLOGP
    ]
    missing_qrfc = [
        d for d in missing
        if (d.qrf_research or {}).get("queue_matches")
    ]
    missing_no_qrfc = [
        d for d in missing
        if not (d.qrf_research or {}).get("queue_matches")
    ]
    mismatch = [
        d for d in ordered
        if d.category == DiscrepancyCategory.ATTRIBUTE_MISMATCH
    ]

    items: List[OperationalActionItem] = []

    if missing_qrfc:
        orders = _sorted_unique_orders(missing_qrfc)
        diagnostics = _unique_qrfc_diagnostics(missing_qrfc)
        steps = [
            (
                "In SMQ2, locate stalled commodity interface queues "
                "(CMM_VLOGP_BGRFC_*) tied to the affected VBELN/POSNR rows in Section 2.1."
            ),
            (
                "For each failed queue entry, open the mapped diagnostic transaction "
                "from the finetuning grid (typically SM12 / SMQ2) and review the "
                "Standard System Text message."
            ),
        ]
        if diagnostics:
            diag_lines = "; ".join(
                f"{text} ({tcode})" if tcode != "—" else text
                for text, tcode in diagnostics[:5]
            )
            steps.append(
                f"Address the specific errors seen in this run: {diag_lines}."
            )
        steps.extend([
            (
                "Release root-document locks (SM12) or correct pricing conditions "
                "before reprocessing, as indicated by the queue error."
            ),
            (
                "Reprocess the failed queue entries and confirm a CMM_VLOGP row "
                "exists for each affected sales order line."
            ),
            "Re-run this reconciliation report to verify missing counts drop to zero.",
        ])
        items.append(
            OperationalActionItem(
                owner_key="SAP Basis",
                owner_label=_format_owner_label("SAP Basis"),
                issue=(
                    f"{len(missing_qrfc)} commodity order line(s) are missing from "
                    "CMM_VLOGP because qRFC interface queues failed during ledger posting."
                ),
                steps=steps,
                affected=_affected_orders_text(
                    orders, section_ref="Section 2.1"
                ),
                target=_target_for_owner("SAP Basis", len(missing_qrfc)),
            )
        )

    if mismatch:
        orders = _sorted_unique_orders(mismatch)
        attrs = _unique_mismatch_attributes(mismatch)
        attr_text = ", ".join(attrs[:6]) if attrs else "listed attributes"
        if len(attrs) > 6:
            attr_text += ", …"
        steps = [
            (
                f"For each mismatch in Section 2.2, compare VBAP against the CMM_VLOGP "
                f"baseline for: {attr_text}."
            ),
            (
                "Review linked CDHDR/CDPOS records (TABNAME, FNAME, VALUE_OLD, VALUE_NEW) "
                "to determine whether the commercial contract or the risk ledger changed first."
            ),
            (
                "Synchronize physical inventory location / quantity tags in CMM_VLOGP "
                "when VBAP reflects commercial truth, or trigger commodity re-valuation "
                "if the ledger update was skipped."
            ),
            (
                "Validate that localized VaR and NOP calculations reflect the corrected "
                "storage and quantity profile."
            ),
            "Re-run reconciliation to confirm attribute drift is cleared.",
        ]
        items.append(
            OperationalActionItem(
                owner_key="SAP Commodity Team",
                owner_label=_format_owner_label("SAP Commodity Team"),
                issue=(
                    f"{len(mismatch)} order line(s) show attribute drift between VBAP "
                    "and CMM_VLOGP — risk positions may not reflect current commercial data."
                ),
                steps=steps,
                affected=_affected_orders_text(
                    orders, section_ref="Section 2.2"
                ),
                target=_target_for_owner("SAP Commodity Team", len(mismatch)),
            )
        )

    if missing_no_qrfc:
        orders = _sorted_unique_orders(missing_no_qrfc)
        example = f" (e.g. {orders[0][0]}/{orders[0][1]})" if orders else ""
        steps = [
            (
                f"For each order line in Section 2.1 with no qRFC queue footprint{example}, "
                "trace the VBAP → commodity document → CMM_VLOGP creation path in "
                "application logs."
            ),
            (
                "Confirm TRMRISK-RELEVANT = 'C', pricing key, and MtM pricing conditions "
                "are active on each affected line."
            ),
            (
                "Perform a manual ledger backfill or controlled re-booking when business "
                "confirms the exposure should be in the Net Open Position."
            ),
            (
                "Document the root cause of any silent pipeline dropout and add monitoring "
                "for orders that never reach the interface queue."
            ),
        ]
        items.append(
            OperationalActionItem(
                owner_key="Functional Analyst",
                owner_label=_format_owner_label("Functional Analyst"),
                issue=(
                    f"{len(missing_no_qrfc)} order line(s) are missing from CMM_VLOGP "
                    "with no qRFC error — likely a silent booking or configuration gap."
                ),
                steps=steps,
                affected=_affected_orders_text(
                    orders, section_ref="Section 2.1"
                ),
                target=_target_for_owner("Functional Analyst", len(missing_no_qrfc)),
            )
        )

    return items


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


def _compact_mismatch_attr(attr: str) -> str:
    """Short attribute label for Category 2 table cells (e.g. LGORT)."""
    text = (attr or "").strip()
    if " (VBAP)" in text:
        return text.split(" (VBAP)")[0].strip()
    if "/" in text:
        return text.split("/")[0].strip()
    return text or "—"


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


def _portfolio_status_label(status: str) -> str:
    """HTML for portfolio status header — white bold text on status-colored bar."""
    return f"<b>Portfolio Status: {_escape(status.upper())}</b>"


def _portfolio_status_bar_color(status: str) -> colors.Color:
    """Header and border color keyed to GREEN / AMBER / RED."""
    key = (status or "RED").upper()
    if key == "GREEN":
        return _hex("green")
    if key == "AMBER":
        return _hex("amber")
    return _hex("red")


def _clean_context(text: str, max_len: int = 120) -> str:
    """Trim SAP diagnostic text for executive bullets."""
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rstrip() + "..."


def _section3_error_label(std_text: str) -> str:
    """Map finetuning / queue text to a crisp Section 3.1 bullet label."""
    lower = (std_text or "").lower()
    if "root document locked" in lower or "document locked" in lower:
        return "Root Cause: Document Lock"
    if "pricing" in lower or "mtm" in lower or "condition" in lower:
        return "Pricing Block Error"
    return "Technical Diagnosis Summary"


def _build_section3_missing_bullets(
    missing: List[DiscrepancyRecord],
) -> List[tuple[str, str]]:
    """Up to three labeled bullets for Section 3.1 from qRFC / missing-row data."""
    bullets: List[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    pricing_or_lock = 0

    for d in _sort_discrepancies(missing):
        queues = (d.qrf_research or {}).get("queue_matches") or []
        if not queues:
            pair = (
                "Unbooked Exposure",
                f"Order {d.vbeln} has no CMM_VLOGP row — check qRFC queues and manual reconciliation.",
            )
            if pair not in seen:
                seen.add(pair)
                bullets.append(pair)
            continue

        for entry in queues:
            std_text, _, _ = _category1_finetuning_columns(entry)
            label = _section3_error_label(std_text)
            if label == "Root Cause: Document Lock":
                text = (
                    f"Order {d.vbeln} is locked at the root level (SM12), "
                    "causing an unbooked risk blind spot."
                )
                pricing_or_lock += 1
            elif label == "Pricing Block Error":
                text = (
                    f"Order {d.vbeln} failed to interface due to inactive MtM condition "
                    f"or pricing error ({_clean_context(std_text, 60)})."
                )
                pricing_or_lock += 1
            else:
                text = (
                    f"Order {d.vbeln}/{d.posnr}: {_clean_context(std_text, 90)} "
                    "— qRFC interface block."
                )
            pair = (label, text)
            if pair not in seen:
                seen.add(pair)
                bullets.append(pair)
            if len(bullets) >= 2:
                break
        if len(bullets) >= 2:
            break

    if pricing_or_lock >= 2 and len(bullets) < 3:
        bullets.append((
            "Technical Diagnosis Summary",
            (
                f"{len(missing)} order(s) fail at the pricing determination layer due to "
                "missing Start Date or locked root documents, forcing qRFC interface blocks."
            ),
        ))

    return bullets[:3]


def _hex(name: str) -> colors.Color:
    return colors.HexColor(PDF_THEME[name])


def _accent_rule(width: float = CONTENT_WIDTH, thickness: float = 2) -> Table:
    """Thin horizontal rule for section separation."""
    rule = Table([[""]], colWidths=[width], rowHeights=[thickness / 72 * inch])
    rule.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _hex("navy")),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    return rule


def _pdf_page_decorations(canvas, doc) -> None:
    """Footer rule and page number (sample-style, no top stripe)."""
    canvas.saveState()
    page_w, _page_h = letter

    canvas.setStrokeColor(_hex("border_light"))
    canvas.setLineWidth(0.5)
    canvas.line(PDF_MARGIN, 0.58 * inch, page_w - PDF_MARGIN, 0.58 * inch)

    canvas.setFont(NOTO_REGULAR, 8)
    canvas.setFillColor(_hex("slate_light"))
    canvas.drawString(PDF_MARGIN, 0.42 * inch, "Commodity Exposure & Portfolio Drift Analysis")
    canvas.drawRightString(page_w - PDF_MARGIN, 0.42 * inch, f"Page {canvas.getPageNumber()}")

    canvas.restoreState()


def _pdf_page_footer(canvas, doc) -> None:
    """Backward-compatible alias for page callbacks."""
    _pdf_page_decorations(canvas, doc)


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
        register_pdf_fonts()
        styles = getSampleStyleSheet()
        t = PDF_TYPE
        self._report_title = ParagraphStyle(
            "ReportTitle",
            parent=styles["Heading1"],
            fontSize=t["title"],
            leading=t["title"] + 6,
            spaceAfter=4,
            spaceBefore=0,
            alignment=1,
            textColor=colors.black,
            fontName=NOTO_BOLD,
        )
        self._report_subtitle = ParagraphStyle(
            "ReportSubtitle",
            parent=styles["BodyText"],
            fontSize=t["subtitle"],
            leading=t["subtitle"] + 4,
            spaceAfter=4,
            spaceBefore=0,
            alignment=1,
            textColor=_hex("cat1_accent"),
            fontName=NOTO_BOLD,
        )
        self._report_date = ParagraphStyle(
            "ReportDate",
            parent=styles["BodyText"],
            fontSize=t["date"],
            leading=t["date"] + 3,
            spaceAfter=0,
            spaceBefore=0,
            alignment=1,
            textColor=colors.black,
            fontName=NOTO_ITALIC,
        )
        self._section_heading = ParagraphStyle(
            "SectionHeading",
            parent=styles["Heading2"],
            fontSize=t["section"],
            leading=t["section"] + 4,
            spaceBefore=12,
            spaceAfter=2,
            textColor=_hex("navy"),
            fontName=NOTO_BOLD,
        )
        self._subsection_heading = ParagraphStyle(
            "SubsectionHeading",
            parent=styles["Heading3"],
            fontSize=t["subsection"],
            leading=t["subsection"] + 3,
            spaceBefore=14,
            spaceAfter=8,
            textColor=colors.black,
            fontName=NOTO_BOLD,
        )
        self._body = ParagraphStyle(
            "ExecBody",
            parent=styles["BodyText"],
            fontSize=t["body"],
            leading=t["body"] + 4,
            spaceAfter=8,
            textColor=colors.black,
            fontName=NOTO_REGULAR,
        )
        self._bullet = ParagraphStyle(
            "ExecBullet",
            parent=self._body,
            leftIndent=14,
            bulletIndent=0,
            spaceAfter=6,
            leading=t["body"] + 4,
            textColor=colors.black,
            fontName=NOTO_REGULAR,
        )
        self._exec_numbered_list = ParagraphStyle(
            "ExecNumberedList",
            parent=self._body,
            leftIndent=14,
            spaceBefore=2,
            spaceAfter=2,
            leading=t["body"] + 4,
            textColor=colors.black,
            fontName=NOTO_REGULAR,
        )
        self._portfolio_status_header = ParagraphStyle(
            "PortfolioStatusHeader",
            parent=styles["BodyText"],
            fontSize=t["body"],
            leading=t["body"] + 4,
            textColor=_hex("white"),
            fontName=NOTO_BOLD,
            spaceBefore=0,
            spaceAfter=0,
        )
        self._portfolio_status_bullet = ParagraphStyle(
            "PortfolioStatusBullet",
            parent=styles["BodyText"],
            fontSize=t["body"],
            leading=t["body"] + 7,
            textColor=colors.black,
            leftIndent=14,
            spaceBefore=0,
            spaceAfter=0,
            fontName=NOTO_REGULAR,
        )
        self._action_box_header = ParagraphStyle(
            "ActionBoxHeader",
            parent=styles["BodyText"],
            fontSize=t["body"],
            leading=t["body"] + 4,
            textColor=_hex("white"),
            fontName=NOTO_BOLD,
            spaceBefore=0,
            spaceAfter=0,
        )
        self._action_item_title = ParagraphStyle(
            "ActionItemTitle",
            parent=styles["BodyText"],
            fontSize=t["body"],
            leading=t["body"] + 4,
            textColor=colors.black,
            fontName=NOTO_BOLD,
            spaceBefore=4,
            spaceAfter=2,
        )
        self._action_item_detail = ParagraphStyle(
            "ActionItemDetail",
            parent=styles["BodyText"],
            fontSize=t["body"],
            leading=t["body"] + 5,
            textColor=colors.black,
            fontName=NOTO_REGULAR,
            leftIndent=18,
            spaceBefore=0,
            spaceAfter=2,
        )
        self._caption = ParagraphStyle(
            "TableCaption",
            parent=styles["BodyText"],
            fontSize=t["caption"],
            leading=t["caption"] + 3,
            spaceBefore=8,
            spaceAfter=14,
            textColor=_hex("slate_light"),
            fontName=NOTO_ITALIC,
        )
        self._small = ParagraphStyle(
            "Small",
            parent=styles["BodyText"],
            fontSize=t["body"],
            leading=t["body"] + 3,
            textColor=colors.black,
            fontName=NOTO_REGULAR,
        )
        self._detail_label = ParagraphStyle(
            "DetailLabel",
            parent=self._small,
            fontSize=t["table"],
            leading=t["table"] + 3,
            textColor=_hex("slate"),
            fontName=NOTO_BOLD,
            spaceBefore=10,
            spaceAfter=6,
        )
        self._cell = ParagraphStyle(
            "Cell",
            parent=styles["BodyText"],
            fontSize=t["table"],
            leading=t["table"] + 2,
            wordWrap="CJK",
            textColor=colors.black,
            fontName=NOTO_REGULAR,
        )
        self._cell_header = ParagraphStyle(
            "CellHeader",
            parent=self._cell,
            fontName=NOTO_BOLD,
            fontSize=t["table"],
            leading=t["table"] + 2,
            textColor=_hex("white"),
        )
        self._cell_header_dark = ParagraphStyle(
            "CellHeaderDark",
            parent=self._cell,
            fontName=NOTO_BOLD,
            fontSize=t["table"],
            leading=t["table"] + 2,
            textColor=_hex("navy"),
        )
        detail = max(t["table"] - 1, 7)
        self._cell_detail = ParagraphStyle(
            "CellDetail",
            parent=styles["BodyText"],
            fontSize=detail,
            leading=detail + 2,
            wordWrap="CJK",
            splitLongWords=False,
            textColor=colors.black,
            fontName=NOTO_REGULAR,
        )
        self._cell_header_detail = ParagraphStyle(
            "CellHeaderDetail",
            parent=self._cell_detail,
            fontName=NOTO_BOLD,
            textColor=_hex("white"),
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
            topMargin=PDF_MARGIN,
            bottomMargin=PDF_MARGIN,
            leftMargin=PDF_MARGIN,
            rightMargin=PDF_MARGIN,
        )
        story: List[Any] = []
        generated = datetime.now().strftime("%B %d, %Y")
        ordered = _sort_discrepancies(discrepancies)
        missing = [
            d for d in ordered
            if d.category == DiscrepancyCategory.MISSING_IN_CMM_VLOGP
        ]
        mismatch = [
            d for d in ordered
            if d.category == DiscrepancyCategory.ATTRIBUTE_MISMATCH
        ]
        total_issues = len(discrepancies)
        align_pct = _alignment_pct(summary)
        status = _portfolio_status(summary)

        # Cover / title block
        story.append(Spacer(1, 0.08 * inch))
        story.append(self._cover_block(generated))
        story.append(Spacer(1, 0.22 * inch))

        story.extend(
            self._executive_summary_section(
                narrative, summary, missing, mismatch, total_issues, align_pct, status
            )
        )
        story.extend(
            self._reconciliation_categories_section(summary, missing, mismatch)
        )
        story.extend(
            self._executive_risk_analysis_section(missing, mismatch)
        )
        story.extend(
            self._executive_mitigation_section(discrepancies)
        )

        doc.build(story, onFirstPage=_pdf_page_footer, onLaterPages=_pdf_page_footer)
        buffer.seek(0)
        return buffer.getvalue()

    def _section(self, number: int, title: str, *, first: bool = False) -> List[Any]:
        """Section heading with navy underline (sample PDF style)."""
        style = ParagraphStyle(
            "SectionHeadingRun",
            parent=self._section_heading,
            spaceBefore=0 if first else self._section_heading.spaceBefore,
        )
        return [
            Paragraph(f"{number} {_escape(title)}", style),
            HRFlowable(
                width="100%",
                thickness=0.75,
                color=_hex("navy"),
                spaceBefore=0,
                spaceAfter=6,
            ),
        ]

    def _subsection(self, number: str, title: str, *, accent: str = "navy") -> Paragraph:
        """Subsection heading — plain bold left-aligned."""
        return Paragraph(f"{number} {_escape(title)}", self._subsection_heading)

    def _cover_block(self, generated: str) -> Table:
        """Centered report header — title, subtitle, EOD verification date."""
        lines = [
            Paragraph("Commodity Exposure &amp; Portfolio Drift Analysis", self._report_title),
            Paragraph(
                "Reconciliation Delta &amp; Technical Validation (VBAP vs. CMM_VLOGP)",
                self._report_subtitle,
            ),
            Paragraph(
                f"EOD Close Verification — Generated on {_escape(generated)}",
                self._report_date,
            ),
        ]
        header = Table([[line] for line in lines], colWidths=[CONTENT_WIDTH])
        header.setStyle(
            TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ])
        )
        return header

    def _portfolio_status_box(
        self,
        status: str,
        metrics: List[tuple[str, str]],
    ) -> Table:
        """
        Portfolio status callout — status-colored header bar + dash-bulleted metrics body.
        Each metric is (label, value); label renders bold before the colon.
        """
        bar_color = _portfolio_status_bar_color(status)
        header = Paragraph(
            _portfolio_status_label(status),
            self._portfolio_status_header,
        )
        bullet_html = "<br/>".join(
            f"– <b>{_escape(label)}:</b> {_escape(value)}" for label, value in metrics
        )
        body = Paragraph(bullet_html, self._portfolio_status_bullet)

        panel = Table(
            [[header], [body]],
            colWidths=[CONTENT_WIDTH],
        )
        panel.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), bar_color),
                ("BACKGROUND", (0, 1), (-1, 1), _hex("white")),
                ("BOX", (0, 0), (-1, -1), 1, bar_color),
                ("LEFTPADDING", (0, 0), (-1, 0), 14),
                ("RIGHTPADDING", (0, 0), (-1, 0), 14),
                ("TOPPADDING", (0, 0), (-1, 0), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
                ("LEFTPADDING", (0, 1), (-1, 1), 14),
                ("RIGHTPADDING", (0, 1), (-1, 1), 14),
                ("TOPPADDING", (0, 1), (-1, 1), 12),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 12),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ])
        )
        wrapper = Table([[panel]], colWidths=[CONTENT_WIDTH])
        wrapper.setStyle(
            TableStyle([
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ])
        )
        return wrapper

    def _operational_risk_action_box(
        self,
        items: List[OperationalActionItem],
    ) -> List[Any]:
        """
        Orange-bordered callout for Section 4 action items (mockup design).
        Returns splittable flowables so long step lists can span pages.
        """
        header = Paragraph(
            "<b>Operational Risk Action Items</b>",
            self._action_box_header,
        )
        rows: List[List[Any]] = [[header]]

        if not items:
            rows.append([
                Paragraph(
                    "No discrepancies were identified — no remediation steps required for this run.",
                    self._action_item_detail,
                )
            ])
        else:
            for idx, item in enumerate(items, start=1):
                title_style = self._action_item_title
                if idx > 1:
                    title_style = ParagraphStyle(
                        "ActionItemTitleGap",
                        parent=self._action_item_title,
                        spaceBefore=12,
                    )
                rows.append([
                    Paragraph(
                        f"{idx}. <b>{_escape(item.owner_label)}</b>",
                        title_style,
                    )
                ])
                rows.append([
                    Paragraph(
                        f"<i>Issue:</i> {_escape(item.issue)}",
                        self._action_item_detail,
                    )
                ])
                step_lines = "<br/>".join(
                    f"&nbsp;&nbsp;{step_no}. {_escape(step)}"
                    for step_no, step in enumerate(item.steps, start=1)
                )
                rows.append([
                    Paragraph(
                        f"<i>Steps to resolve:</i><br/>{step_lines}",
                        self._action_item_detail,
                    )
                ])
                rows.append([
                    Paragraph(
                        f"<i>Affected orders:</i> {_escape(item.affected)}",
                        self._action_item_detail,
                    )
                ])
                rows.append([
                    Paragraph(
                        f"<i>Target:</i> {_escape(item.target)}",
                        self._action_item_detail,
                    )
                ])

        panel = Table(rows, colWidths=[CONTENT_WIDTH], repeatRows=1)
        panel.splitByRow = 1
        orange = _hex("action_orange")
        panel.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), orange),
                ("BACKGROUND", (0, 1), (-1, -1), _hex("surface")),
                ("BOX", (0, 0), (-1, -1), 1, orange),
                ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ("LEFTPADDING", (0, 0), (-1, -1), 16),
                ("RIGHTPADDING", (0, 0), (-1, -1), 16),
                ("TOPPADDING", (0, 0), (0, 0), 12),
                ("BOTTOMPADDING", (0, 0), (0, 0), 12),
                ("TOPPADDING", (0, 1), (-1, -1), 4),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 14),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ])
        )
        return [panel, Spacer(1, 0.1 * inch)]

    def _summary_box(self, flowables: List[Any]) -> Table:
        """Generic bordered callout (legacy helper)."""
        if not flowables:
            return Table([[Spacer(1, 0.01 * inch)]], colWidths=[CONTENT_WIDTH])

        rows = [[item] for item in flowables]
        table = Table(rows, colWidths=[CONTENT_WIDTH])
        table.setStyle(
            TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.75, _hex("border")),
                ("LINEBEFORE", (0, 0), (0, -1), 4, _hex("navy_light")),
                ("BACKGROUND", (0, 0), (-1, -1), _hex("surface")),
                ("LEFTPADDING", (0, 0), (-1, -1), 16),
                ("RIGHTPADDING", (0, 0), (-1, -1), 16),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ])
        )
        wrapper = Table([[table]], colWidths=[CONTENT_WIDTH])
        wrapper.setStyle(
            TableStyle([
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ])
        )
        return wrapper

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
        blocks: List[Any] = []
        blocks.extend(self._section(1, "Executive Summary", first=True))
        blocks.append(Paragraph(_escape(EXECUTIVE_SUMMARY_LEAD), self._body))

        intro = narrative.get("executive_summary") or summary.executive_summary
        if intro and str(intro).strip() and str(intro).strip() != EXECUTIVE_SUMMARY_LEAD:
            blocks.append(Paragraph(_escape(str(intro)), self._body))

        metrics: List[tuple[str, str]] = [
            (
                "Total Booked Contracts Analyzed",
                f"{summary.total_commodity_relevant} Active Sales Orders",
            ),
            (
                "Total Discrepancies Located",
                f"{total_issues} Discrepancy Deltas",
            ),
            (
                "Unbooked Exposure Gap (Missing Records)",
                f"{summary.missing_count} Contracts (Risk Management Blindspot)",
            ),
            (
                "Active Portfolio Drift (Attribute Mismatches)",
                f"{summary.mismatch_count} Contracts (Physical Location Tracking Drift)",
            ),
            (
                "Overall Ledger Integrity Index",
                f"{align_pct:.2f}% Alignment (Critical limit is 99.00%)",
            ),
        ]
        blocks.append(self._portfolio_status_box(status, metrics))
        blocks.append(Spacer(1, 0.14 * inch))
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
        blocks: List[Any] = []
        blocks.extend(self._section(2, "Portfolio Reconciliation Detail"))
        blocks.append(
            Paragraph(
                _escape(
                    f"Of {summary.total_commodity_relevant} commodity-relevant VBAP row(s) in scope, "
                    f"{summary.missing_count} are missing in CMM_VLOGP and "
                    f"{summary.mismatch_count} have attribute differences. "
                    "Every affected order line is listed below."
                ),
                self._body,
            )
        )
        blocks.append(Spacer(1, 0.1 * inch))
        blocks.append(
            self._subsection(
                "2.1",
                "Missing Sales Document (VBAP) in Risk Position Ledger (CMM_VLOGP)",
                accent="cat1_accent",
            )
        )

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
        blocks.append(
            self._subsection("2.2", "Category 2 — Attribute Mismatch", accent="cat2_accent")
        )

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
            cat2_detail_rows = _build_category2_table_rows(mismatch)
            cat2_rows: List[List[str]] = [CATEGORY2_DETAIL_HEADERS]
            cat2_rows.extend(cat2_detail_rows)
            blocks.append(self._category2_detail_table(cat2_rows))
            blocks.append(
                Paragraph(
                    _record_count_footer(
                        len(cat2_detail_rows),
                        summary.mismatch_detail_count or summary.mismatch_count,
                        "mismatch detail rows",
                    ),
                    self._caption,
                )
            )

        blocks.append(Spacer(1, 0.08 * inch))
        return blocks

    def _labeled_dash_bullet(self, label: str, text: str) -> Paragraph:
        """Section 3 style — dash bullet with bold label prefix."""
        return Paragraph(
            f"– <b>{_escape(label)}:</b> {_escape(text)}",
            self._bullet,
        )

    def _executive_risk_analysis_section(
        self,
        missing: List[DiscrepancyRecord],
        mismatch: List[DiscrepancyRecord],
    ) -> List[Any]:
        blocks: List[Any] = []
        blocks.extend(self._section(3, "Portfolio Drift & Risk Vector Analysis"))

        if missing:
            blocks.append(self._subsection("3.1", "Systemic Interface Calculation Lags"))
            blocks.append(
                Paragraph(
                    _escape(
                        "Multiple active orders are failing to synchronize with the Risk "
                        "Position Ledger. Transaction-level blocks in qRFC queues prevent "
                        "risk booking:"
                    ),
                    self._body,
                )
            )
            for label, text in _build_section3_missing_bullets(missing):
                blocks.append(self._labeled_dash_bullet(label, text))

        lgort_mismatch = [
            d for d in mismatch
            if any("LGORT" in (f or "").upper() for f in (d.mismatched_fields or []))
        ]
        if lgort_mismatch:
            blocks.append(self._subsection("3.2", "Inventory Location Drift (LGORT Mismatches)"))
            order_sample = ", ".join(d.vbeln for d in lgort_mismatch[:3])
            blocks.append(
                Paragraph(
                    _escape(
                        f"Orders {order_sample} are physically remapped from "
                        '"In-Transit" (INTR) to "Final Inventory" (FINV).'
                    ),
                    self._body,
                )
            )
            blocks.append(
                self._labeled_dash_bullet(
                    "Impact on risk limits",
                    "Risk software applies transit factors where facility storage factors "
                    "are appropriate, distorting regional allocations.",
                )
            )
            blocks.append(
                self._labeled_dash_bullet(
                    "Operational impact",
                    "Custody and jurisdictional profiles may register under incorrect "
                    "storage categories until synchronized.",
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
        discrepancies: List[DiscrepancyRecord],
    ) -> List[Any]:
        blocks: List[Any] = []
        blocks.extend(self._section(4, "Immediate Action & Risk Mitigation Plan"))
        blocks.append(
            Paragraph(
                _escape(
                    "Each item below assigns a responsible team, describes the exposure, "
                    "lists concrete remediation steps derived from this run's diagnostics, "
                    "and states the completion target. Content is rule-based and identical "
                    "for the same reconciliation data. Cross-reference Section 2 for "
                    "order-level detail."
                ),
                self._body,
            )
        )
        action_items = _build_operational_action_items(discrepancies)
        blocks.extend(self._operational_risk_action_box(action_items))

        blocks.append(Spacer(1, 0.04 * inch))
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

    def _category2_cell_paragraph(self, col_idx: int, value: str, *, header: bool) -> Paragraph:
        """Format a Category 2 cell — compact attribute labels, no-wrap for IDs."""
        style = self._cell_header_detail if header else self._cell_detail
        text = str(value or "")
        if not header:
            if col_idx == 3:
                text = _compact_mismatch_attr(text)
            elif col_idx in CATEGORY2_NOWRAP_COLS and text and text != "—":
                return Paragraph(f"<nobr>{_escape(text)}</nobr>", style)
        elif col_idx in CATEGORY2_NOWRAP_COLS:
            return Paragraph(f"<nobr>{_escape(text)}</nobr>", style)
        return Paragraph(_escape(text), style)

    def _category2_detail_table(self, data: List[List[str]]) -> Table:
        """Section 2.2 table — compact 7pt layout with controlled column widths."""
        wrapped: List[List[Any]] = []
        for row_idx, row in enumerate(data):
            header = row_idx == 0
            wrapped.append([
                self._category2_cell_paragraph(col_idx, cell, header=header)
                for col_idx, cell in enumerate(row)
            ])

        table = Table(wrapped, colWidths=CATEGORY2_DETAIL_WIDTHS, repeatRows=1)
        table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), _hex("navy")),
                ("BACKGROUND", (0, 1), (-1, -1), _hex("white")),
                ("TEXTCOLOR", (0, 0), (-1, 0), _hex("white")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, _hex("navy_light")),
                ("GRID", (0, 0), (-1, -1), 0.3, _hex("border_light")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (0, -1), 2),
                ("RIGHTPADDING", (0, 0), (0, -1), 2),
                ("LEFTPADDING", (1, 0), (-1, -1), 4),
                ("RIGHTPADDING", (1, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("TOPPADDING", (0, 1), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
                ("FONTNAME", (0, 0), (-1, 0), NOTO_BOLD),
            ])
        )
        return table

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
                    Paragraph(_escape(str(row[0])), self._cell_header_dark),
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
                ("GRID", (0, 0), (-1, -1), 0.3, _hex("border_light")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("FONTNAME", (0, 0), (0, -1), NOTO_BOLD),
                ("BACKGROUND", (0, 0), (0, -1), _hex("surface_alt")),
                ("BACKGROUND", (1, 0), (-1, -1), _hex("white")),
            ]
        else:
            style_commands = [
                ("BACKGROUND", (0, 0), (-1, 0), _hex("navy")),
                ("BACKGROUND", (0, 1), (-1, -1), _hex("white")),
                ("TEXTCOLOR", (0, 0), (-1, 0), _hex("white")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, _hex("navy_light")),
                ("GRID", (0, 0), (-1, -1), 0.3, _hex("border_light")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, 0), 7),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
                ("TOPPADDING", (0, 1), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
                ("FONTNAME", (0, 0), (-1, 0), NOTO_BOLD),
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
