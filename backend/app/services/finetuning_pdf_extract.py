"""
One-time (or on-demand) extraction of section 2 — Integrated Message Mapping Grid
from Finetuning_Reports_for_Risk_Analysis.pdf into CSV.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from app.services.field_compare import norm

SECTION_MARKER = "2. Integrated Message Mapping Grid"
SECTION_END_MARKER = "3. Deep-Dive Runbook"
JUNK_PATTERNS = (
    "google",
    "gemini",
    "ini.google",
    "https://",
    "finetuning reports for risk",
)

OUTPUT_COLUMNS = [
    "MESSAGE_ID",
    "MESSAGE_NUMBER",
    "STANDARD_SYSTEM_TEXT",
    "SAP_COMPONENT_AREA",
    "DIAGNOSTIC_TCODE",
]


def _clean_cell(val: object) -> str:
    return re.sub(r"\s+", " ", str(val or "").replace("\n", " ")).strip()


def _is_junk(text: str) -> bool:
    lower = text.lower()
    return not text or any(p in lower for p in JUNK_PATTERNS)


def _normalize_record(
    message_id: str,
    message_number: str,
    standard_text: str,
    component_area: str,
    diagnostic_tcode: str,
) -> Optional[Dict[str, str]]:
    mid = norm(message_id).upper()
    mnum = norm(message_number)
    if not mid or not mnum:
        return None
    if _is_junk(mid) or _is_junk(mnum):
        return None
    if not re.match(r"^[\w]+$", mid):
        return None
    if not re.match(r"^\d{1,3}$", mnum):
        return None
    if mid == "MESSAGE" or mnum == "NUMBER":
        return None

    return {
        "MESSAGE_ID": mid,
        "MESSAGE_NUMBER": mnum,
        "STANDARD_SYSTEM_TEXT": _clean_cell(standard_text),
        "SAP_COMPONENT_AREA": _clean_cell(component_area),
        "DIAGNOSTIC_TCODE": _clean_cell(diagnostic_tcode),
    }


def _parse_table_row(cells: List[str]) -> Optional[Dict[str, str]]:
    if len(cells) < 3:
        return None
    if cells[0].lower() in ("message id", ":21 pm") or cells[0].startswith(":"):
        return None
    if cells[0] in ("program terminated (read failed)",):
        return None
    if "could not be determined" in " ".join(cells).lower():
        return None

    if re.match(r"^\d{1,3}$", cells[0]) and len(cells) >= 4 and re.match(r"^\d{1,3}$", cells[1]):
        return _normalize_record(cells[0], cells[1], cells[2], cells[3], cells[4] if len(cells) > 4 else "")
    if len(cells) >= 5 and re.match(r"^[\w]+$", cells[0]) and re.match(r"^\d{1,3}$", cells[1]):
        return _normalize_record(cells[0], cells[1], cells[2], cells[3], cells[4])
    if len(cells) >= 6:
        return _normalize_record(cells[1], cells[2], cells[3], cells[4], cells[5])
    return None


def _iter_grid_pages(pdf) -> List:
    """Pages belonging to section 2 (grid continues onto page 3 in this PDF)."""
    pages = []
    in_grid = False
    for page in pdf.pages:
        text = page.extract_text() or ""
        if SECTION_MARKER in text:
            in_grid = True
        if not in_grid:
            continue
        pages.append(page)
        if SECTION_END_MARKER in text:
            break
    return pages


def _records_from_tables(pdf_path: Path) -> List[Dict[str, str]]:
    import pdfplumber

    records: List[Dict[str, str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in _iter_grid_pages(pdf):
            for table in page.extract_tables() or []:
                for row in table:
                    cells = [
                        _clean_cell(c)
                        for c in row
                        if c is not None and not _is_junk(_clean_cell(c))
                    ]
                    rec = _parse_table_row(cells)
                    if rec:
                        records.append(rec)
    return records


def _records_from_section_text(pdf_path: Path) -> List[Dict[str, str]]:
    """Fallback text parse for section 2 only."""
    import pdfplumber

    records: List[Dict[str, str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        text_parts: List[str] = []
        for page in _iter_grid_pages(pdf):
            text_parts.append(page.extract_text() or "")
        text = "\n".join(text_parts)
        if SECTION_MARKER in text:
            text = text.split(SECTION_MARKER, 1)[1]
        if SECTION_END_MARKER in text:
            text = text.split(SECTION_END_MARKER, 1)[0]

        for raw_line in text.splitlines():
            line = _clean_cell(raw_line)
            if not line or _is_junk(line):
                continue
            m = re.match(
                r"^([A-Z0-9_]+)\s+(\d{1,3})\s+(.+)$",
                line,
            )
            if not m:
                continue
            mid, mnum, rest = m.group(1), m.group(2), m.group(3)
            # Heuristic split: last token(s) = tcode, token before = component prefix
            parts = rest.rsplit(" ", 3)
            if len(parts) < 2:
                continue
            rec = _normalize_record(mid, mnum, rest, "", "")
            if rec:
                records.append(rec)
    return records


def extract_finetuning_grid(pdf_path: Path) -> List[Dict[str, str]]:
    """Extract deduplicated message mapping rows from the finetuning PDF."""
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Finetuning PDF not found: {pdf_path}")

    merged: Dict[tuple, Dict[str, str]] = {}
    for rec in _records_from_tables(pdf_path):
        key = (rec["MESSAGE_ID"], rec["MESSAGE_NUMBER"])
        merged[key] = rec

    for rec in _records_from_section_text(pdf_path):
        key = (rec["MESSAGE_ID"], rec["MESSAGE_NUMBER"])
        if key in merged:
            existing = merged[key]
            if not existing["SAP_COMPONENT_AREA"] and rec["SAP_COMPONENT_AREA"]:
                existing["SAP_COMPONENT_AREA"] = rec["SAP_COMPONENT_AREA"]
            if not existing["DIAGNOSTIC_TCODE"] and rec["DIAGNOSTIC_TCODE"]:
                existing["DIAGNOSTIC_TCODE"] = rec["DIAGNOSTIC_TCODE"]
            continue
        merged[key] = rec

    return sorted(merged.values(), key=lambda r: (r["MESSAGE_ID"], int(r["MESSAGE_NUMBER"])))


def convert_finetuning_pdf_to_csv(
    pdf_path: Path,
    csv_path: Path,
    *,
    force: bool = False,
) -> Path:
    """
    Write Integrated Message Mapping Grid to CSV.

    Skips conversion when CSV exists and is newer than the PDF unless ``force=True``.
    """
    csv_path = Path(csv_path)
    pdf_path = Path(pdf_path)

    if (
        not force
        and csv_path.is_file()
        and pdf_path.is_file()
        and csv_path.stat().st_mtime >= pdf_path.stat().st_mtime
    ):
        return csv_path

    rows = extract_finetuning_grid(pdf_path)
    if not rows:
        raise ValueError(f"No message mapping rows extracted from {pdf_path}")

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=OUTPUT_COLUMNS).to_csv(csv_path, index=False)
    return csv_path
