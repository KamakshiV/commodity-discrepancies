"""
Lookup qRFC error codes against the Finetuning Integrated Message Mapping Grid.

The grid is loaded from ``finetuning_message_mapping.csv``. On first use, if the
CSV is missing or older than ``Finetuning_Reports_for_Risk_Analysis.pdf``, the CSV
is generated once from PDF section 2 (Integrated Message Mapping Grid).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from app.config import BACKEND_ROOT, settings
from app.services.field_compare import norm
from app.services.finetuning_pdf_extract import convert_finetuning_pdf_to_csv

CSV_COLUMN_ALIASES = {
    "message_id": ("MESSAGE_ID", "Message ID", "message_id"),
    "message_number": ("MESSAGE_NUMBER", "Message NUMBER", "Message Number", "message_number"),
    "standard_system_text": (
        "STANDARD_SYSTEM_TEXT",
        "Standard System Text",
        "standard_system_text",
    ),
    "sap_component_area": (
        "SAP_COMPONENT_AREA",
        "SAP Component Area",
        "sap_component_area",
    ),
    "diagnostic_tcode": (
        "DIAGNOSTIC_TCODE",
        "Diagnostic T-Code",
        "Diagnostic TCode",
        "diagnostic_tcode",
    ),
}

# QRFC_I_ERR_STATE columns used to key finetuning_message_mapping.csv
QRFC_ERR_FIELD_ALIASES = {
    "message_id": (
        "MESSAGE_ID",
        "QRFC_I_ERR_STATE.MESSAGE_ID",
        "message_id",
    ),
    "message_number": (
        "MESSAGE_NUMBER",
        "QRFC_I_ERR_STATE.MESSAGE_NUMBER",
        "message_number",
    ),
    "message": (
        "MESSAGE",
        "QRFC_I_ERR_STATE.MESSAGE",
        "message",
    ),
}


@dataclass(frozen=True)
class FinetuningMapping:
    message_id: str
    message_number: str
    standard_system_text: str
    sap_component_area: str
    diagnostic_tcode: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "message_id": self.message_id,
            "message_number": self.message_number,
            "standard_system_text": self.standard_system_text,
            "sap_component_area": self.sap_component_area,
            "diagnostic_tcode": self.diagnostic_tcode,
        }


def _resolve_column(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for name in candidates:
        hit = lower_map.get(name.lower())
        if hit is not None:
            return hit
    return None


def _normalize_message_number(val: Any) -> str:
    s = norm(val)
    if not s:
        return ""
    if s.isdigit():
        return s.lstrip("0") or "0"
    return s


def _mapping_csv_candidates() -> list[Path]:
    paths: list[Path] = []
    env_path = getattr(settings, "finetuning_message_map_csv", None)
    if env_path:
        paths.append(Path(env_path))
    paths.append(settings.shared_data_dir / "finetuning_message_mapping.csv")
    paths.append(BACKEND_ROOT / "data" / "finetuning_message_mapping.csv")
    return paths


def _finetuning_pdf_candidates() -> list[Path]:
    paths: list[Path] = []
    configured = getattr(settings, "finetuning_report_pdf", None)
    if configured:
        paths.append(Path(configured))
    paths.extend([
        settings.shared_data_dir / "Finetuning_Reports_for_Risk_Analysis.pdf",
        BACKEND_ROOT.parent / "Finetuning_Reports_for_Risk_Analysis.pdf",
        BACKEND_ROOT / "data" / "Finetuning_Reports_for_Risk_Analysis.pdf",
    ])
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def resolve_finetuning_pdf_path() -> Optional[Path]:
    for path in _finetuning_pdf_candidates():
        if path.is_file():
            return path
    return None


def ensure_finetuning_csv() -> Optional[Path]:
    """
    Return path to finetuning_message_mapping.csv, generating from PDF if needed.
    """
    csv_path = None
    for path in _mapping_csv_candidates():
        if path.is_file():
            csv_path = path
            break
    if csv_path is None:
        csv_path = Path(settings.finetuning_message_map_csv)

    pdf_path = resolve_finetuning_pdf_path()
    if not pdf_path:
        return csv_path if csv_path.is_file() else None

    try:
        convert_finetuning_pdf_to_csv(pdf_path, csv_path)
        return csv_path
    except (FileNotFoundError, ValueError):
        return csv_path if csv_path.is_file() else None


def resolve_finetuning_map_path() -> Optional[Path]:
    return ensure_finetuning_csv()


@lru_cache(maxsize=1)
def load_finetuning_index() -> Dict[Tuple[str, str], FinetuningMapping]:
    path = resolve_finetuning_map_path()
    if not path:
        return {}

    df = pd.read_csv(path, dtype=str).fillna("")
    id_col = _resolve_column(df, *CSV_COLUMN_ALIASES["message_id"])
    num_col = _resolve_column(df, *CSV_COLUMN_ALIASES["message_number"])
    text_col = _resolve_column(df, *CSV_COLUMN_ALIASES["standard_system_text"])
    area_col = _resolve_column(df, *CSV_COLUMN_ALIASES["sap_component_area"])
    tcode_col = _resolve_column(df, *CSV_COLUMN_ALIASES["diagnostic_tcode"])

    if not id_col or not num_col:
        return {}

    index: Dict[Tuple[str, str], FinetuningMapping] = {}
    for _, row in df.iterrows():
        message_id = norm(row.get(id_col)).upper()
        message_number = _normalize_message_number(row.get(num_col))
        if not message_id or not message_number:
            continue
        mapping = FinetuningMapping(
            message_id=message_id,
            message_number=message_number,
            standard_system_text=norm(row.get(text_col)) if text_col else "",
            sap_component_area=norm(row.get(area_col)) if area_col else "",
            diagnostic_tcode=norm(row.get(tcode_col)) if tcode_col else "",
        )
        index[(message_id, message_number)] = mapping
    return index


def _pick_field(source: Any, *keys: str) -> str:
    for key in keys:
        try:
            val = source.get(key) if hasattr(source, "get") else source[key]
        except (KeyError, TypeError, IndexError):
            val = None
        text = norm(val)
        if text:
            return text
    return ""


def extract_qrfc_err_state_fields(source: Any) -> tuple[str, str, str]:
    """
    Read QRFC_I_ERR_STATE keys for finetuning lookup.

    Lookup keys are MESSAGE_ID + MESSAGE_NUMBER only. MESSAGE is returned
    separately for display when the finetuning grid has no exact match.
    """
    return (
        _pick_field(source, *QRFC_ERR_FIELD_ALIASES["message_id"]),
        _pick_field(source, *QRFC_ERR_FIELD_ALIASES["message_number"]),
        _pick_field(source, *QRFC_ERR_FIELD_ALIASES["message"]),
    )


def resolve_finetuning_from_qrfc_err(source: Any) -> Dict[str, str]:
    """Map QRFC_I_ERR_STATE.MESSAGE_ID + MESSAGE_NUMBER to finetuning CSV columns."""
    message_id, message_number, raw_message = extract_qrfc_err_state_fields(source)
    resolved = resolve_qrfc_finetuning_fields(message_id, message_number, raw_message)
    resolved["message_id"] = message_id
    resolved["message_number"] = message_number
    return resolved


def lookup_finetuning_message(
    message_id: Any,
    message_number: Any,
) -> Optional[FinetuningMapping]:
    """Match QRFC_I_ERR_STATE MESSAGE_ID + MESSAGE_NUMBER to the finetuning grid."""
    index = load_finetuning_index()
    if not index:
        return None

    mid = norm(message_id).upper()
    mnum = _normalize_message_number(message_number)
    if not mid or not mnum:
        return None

    hit = index.get((mid, mnum))
    if hit:
        return hit

    padded = mnum.zfill(3) if mnum.isdigit() else mnum
    return index.get((mid, padded))


@lru_cache(maxsize=1)
def _finetuning_by_message_id() -> Dict[str, List[FinetuningMapping]]:
    grouped: Dict[str, List[FinetuningMapping]] = {}
    for (message_id, _), mapping in load_finetuning_index().items():
        grouped.setdefault(message_id, []).append(mapping)
    return grouped


def lookup_finetuning_by_message_id(message_id: Any) -> Optional[FinetuningMapping]:
    """
    Fallback when MESSAGE_NUMBER is not in the grid but MESSAGE_ID is known.

    Used for live qRFC errors such as CMM_VLOGP/045 where only CMM_VLOGP/201
    exists in the finetuning PDF. Returns a representative row when every
    mapping for the MESSAGE_ID shares the same component area and t-code.
    """
    mid = norm(message_id).upper()
    if not mid:
        return None

    matches = _finetuning_by_message_id().get(mid) or []
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    areas = {m.sap_component_area for m in matches if m.sap_component_area}
    tcodes = {m.diagnostic_tcode for m in matches if m.diagnostic_tcode}
    if len(areas) == 1 and len(tcodes) == 1:
        return matches[0]
    return None


def resolve_qrfc_finetuning_fields(
    message_id: Any,
    message_number: Any,
    raw_message: Any = "",
) -> Dict[str, str]:
    """
    Resolve finetuning grid columns for a qRFC error.

    Standard text prefers an exact grid match, then falls back to the live
    QRFC MESSAGE. Component area and diagnostic t-code also use MESSAGE_ID
    fallback when the number is missing from the CSV.
    """
    exact = lookup_finetuning_message(message_id, message_number)
    if exact:
        return {
            "standard_system_text": exact.standard_system_text,
            "sap_component_area": exact.sap_component_area,
            "diagnostic_tcode": exact.diagnostic_tcode,
            "match_type": "exact",
        }

    raw = norm(raw_message)
    by_id = lookup_finetuning_by_message_id(message_id)
    if by_id:
        return {
            "standard_system_text": raw or by_id.standard_system_text,
            "sap_component_area": by_id.sap_component_area,
            "diagnostic_tcode": by_id.diagnostic_tcode,
            "match_type": "message_id_fallback",
        }

    return {
        "standard_system_text": raw,
        "sap_component_area": "",
        "diagnostic_tcode": "",
        "match_type": "none",
    }


def invalidate_finetuning_cache() -> None:
    load_finetuning_index.cache_clear()
    _finetuning_by_message_id.cache_clear()
