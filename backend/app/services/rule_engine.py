from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.models.schemas import DiscrepancyCategory, DiscrepancyRecord
from app.services.change_document_research import (
    ChangeResearchIndex,
    research_vbep_changes_for_vbeln,
)
from app.services.data_loader import (
    COMMODITY_FILTER_COLUMN,
    DEFAULT_COMPARE_MAPPINGS,
    DataStore,
    filter_vbap_scope,
    mappings_to_tuples,
)
from app.services.finetuning_message_map import (
    extract_qrfc_err_state_fields,
    resolve_finetuning_from_qrfc_err,
)
from app.services.field_compare import (
    canonical_document_key,
    canonical_item_key,
    norm,
    values_equal,
)


def _norm(val: Any) -> str:
    """Backward-compatible alias."""
    return norm(val)


VBAP_LINE_PDF_FIELDS = ("MANDT", "PRICING_KEY", "VERSION", "KPOSN", "KSCHL")
MANDT_COLUMN_ALIASES = ("MANDT", "MANDANT")


def _extract_vbap_line_fields(vbap_row: pd.Series) -> dict[str, str]:
    """Pull VBAP columns required on Category 2 PDF tables."""
    fields: dict[str, str] = {name: "" for name in VBAP_LINE_PDF_FIELDS}
    for alias in MANDT_COLUMN_ALIASES:
        if alias in vbap_row.index:
            fields["MANDT"] = _norm(vbap_row.get(alias))
            break
    for name in VBAP_LINE_PDF_FIELDS:
        if name == "MANDT":
            continue
        if name in vbap_row.index:
            fields[name] = _norm(vbap_row.get(name))
    return fields


def _cmm_version_number(version: Any) -> int:
    """Numeric CMM_VLOGP.VERSION for ordering (0000000000 → 0)."""
    s = norm(version)
    if not s:
        return -1
    digits = s.lstrip("0")
    return int(digits) if digits else 0


def _build_cmm_index(cmm: pd.DataFrame) -> Dict[Tuple[str, str], pd.Series]:
    """Primary join: DOCUMENT_CHAR10 + DOCUMENT_ITEM (any VERSION)."""
    index: Dict[Tuple[str, str], pd.Series] = {}
    if cmm.empty:
        return index
    doc_col = "DOCUMENT_CHAR10"
    item_col = "DOCUMENT_ITEM"
    if doc_col not in cmm.columns or item_col not in cmm.columns:
        return index
    for _, row in cmm.iterrows():
        key = (
            canonical_document_key(row.get(doc_col)),
            canonical_item_key(row.get(item_col)),
        )
        if not key[0]:
            continue
        existing = index.get(key)
        if existing is None or _cmm_version_number(row.get("VERSION")) >= _cmm_version_number(
            existing.get("VERSION")
        ):
            index[key] = row
    return index


def _is_initial_cmm_version(version: Any) -> bool:
    """CMM_VLOGP.VERSION = '0000000000' (initial version)."""
    s = norm(version)
    if not s:
        return False
    return s.lstrip("0") == "" or s == "0000000000"


def _build_cmm_predecessor_index(cmm: pd.DataFrame) -> Dict[Tuple[str, str], pd.Series]:
    """
    Secondary join: PREDECESSOR_DOC + PREDECESSOR_DOC_ITM where VERSION is initial.

    PREDECESSOR_DOC is compared as numeric (trailing zeros stripped via
    canonical_document_key).
    """
    index: Dict[Tuple[str, str], pd.Series] = {}
    if cmm.empty:
        return index
    required = ("PREDECESSOR_DOC", "PREDECESSOR_DOC_ITM", "VERSION")
    if not all(col in cmm.columns for col in required):
        return index
    for _, row in cmm.iterrows():
        if not _is_initial_cmm_version(row.get("VERSION")):
            continue
        key = (
            canonical_document_key(row.get("PREDECESSOR_DOC")),
            canonical_item_key(row.get("PREDECESSOR_DOC_ITM")),
        )
        if key[0] and key not in index:
            index[key] = row
    return index


def _cmm_rows_for_match_key(
    cmm: pd.DataFrame,
    vbeln: str,
    posnr: str,
    match_path: str,
) -> pd.DataFrame:
    """All CMM rows sharing the join key used for *match_path*."""
    if cmm.empty or not match_path:
        return pd.DataFrame()
    doc_key = canonical_document_key(vbeln)
    item_key = canonical_item_key(posnr)
    if not doc_key:
        return pd.DataFrame()
    if match_path == "direct":
        doc_col, item_col = "DOCUMENT_CHAR10", "DOCUMENT_ITEM"
    else:
        doc_col, item_col = "PREDECESSOR_DOC", "PREDECESSOR_DOC_ITM"
    if doc_col not in cmm.columns or item_col not in cmm.columns:
        return pd.DataFrame()
    mask_doc = cmm[doc_col].map(canonical_document_key) == doc_key
    mask_item = cmm[item_col].map(canonical_item_key) == item_key
    return cmm[mask_doc & mask_item]


def _select_cmm_compare_row(
    pool: pd.DataFrame,
    joined_row: pd.Series,
) -> pd.Series:
    """
    Row used for VBAP ↔ CMM attribute comparison.

    Prefer VERSION 0000000000 when present; otherwise the lowest VERSION number
    (first commodity snapshot). Latest-version rows can hide drift that still
    exists relative to the initial CMM record.
    """
    if pool.empty:
        return joined_row
    v0 = pool[pool["VERSION"].map(_is_initial_cmm_version)]
    if not v0.empty:
        return v0.iloc[0]
    return min(
        (row for _, row in pool.iterrows()),
        key=lambda row: _cmm_version_number(row.get("VERSION")),
    )


def _find_cmm_row(
    vbeln: str,
    posnr: str,
    direct_index: Dict[Tuple[str, str], pd.Series],
    predecessor_index: Dict[Tuple[str, str], pd.Series],
) -> Tuple[Optional[pd.Series], Optional[str]]:
    """
    Match VBAP line to CMM_VLOGP.

    1. VBELN → DOCUMENT_CHAR10, POSNR → DOCUMENT_ITEM (any VERSION)
    2. Else VBELN → PREDECESSOR_DOC, POSNR → PREDECESSOR_DOC_ITM (VERSION 0000000000)
    """
    key = (canonical_document_key(vbeln), canonical_item_key(posnr))
    if not key[0]:
        return None, None

    direct = direct_index.get(key)
    if direct is not None:
        return direct, "direct"

    predecessor = predecessor_index.get(key)
    if predecessor is not None:
        return predecessor, "predecessor"

    return None, None


class RuleEngine:
    """Deterministic discrepancy detection — AI must not override these results."""

    def __init__(
        self,
        store: DataStore,
        compare_mappings: list = None,
        scope_vbelns: Optional[List[str]] = None,
        scope_erdat: Optional[str] = None,
        scope_erdat_from: Optional[str] = None,
        scope_erdat_to: Optional[str] = None,
    ):
        self.store = store
        raw = compare_mappings if compare_mappings is not None else DEFAULT_COMPARE_MAPPINGS
        self.compare_attributes = mappings_to_tuples(raw)
        self.scope_vbelns = scope_vbelns
        self.scope_erdat = scope_erdat
        self.scope_erdat_from = scope_erdat_from
        self.scope_erdat_to = scope_erdat_to

    def _scoped_commodity(self) -> pd.DataFrame:
        vbap = self.store.get("VBAP")
        if vbap.empty:
            return vbap
        return filter_vbap_scope(
            vbap,
            vbelns=self.scope_vbelns if self.scope_vbelns else None,
            erdat=self.scope_erdat,
            erdat_from=self.scope_erdat_from,
            erdat_to=self.scope_erdat_to,
        )

    def run(self) -> list[DiscrepancyRecord]:
        vbap = self.store.get("VBAP")
        cmm = self.store.get("CMM_VLOGP")

        if vbap.empty:
            return []

        commodity = self._scoped_commodity()
        results: list[DiscrepancyRecord] = []
        join_exclude = {"VBELN", "POSNR", COMMODITY_FILTER_COLUMN}

        cmm_index = _build_cmm_index(cmm)
        predecessor_index = _build_cmm_predecessor_index(cmm)
        change_index = ChangeResearchIndex.build(
            self.store.get("CDHDR"),
            self.store.get("CDPOS"),
        )
        qrfc_cache: Dict[str, dict[str, Any]] = {}
        change_cache: Dict[str, list[dict[str, Any]]] = {}

        qin = self.store.get("QRFC_I_QIN_TOP")
        err = self.store.get("QRFC_I_ERR_STATE")
        cdhdr = self.store.get("CDHDR")
        cdpos = self.store.get("CDPOS")

        for _, row in commodity.iterrows():
            vbeln = _norm(row.get("VBELN"))
            posnr = _norm(row.get("POSNR"))
            vbap_attrs = {
                col: _norm(row.get(col))
                for col in row.index
                if col not in join_exclude
            }

            cmm_row, match_path = _find_cmm_row(
                vbeln, posnr, cmm_index, predecessor_index
            )

            if cmm_row is None:
                # Category 1 — join logic unchanged; qRFC research only for missing rows.
                results.append(
                    DiscrepancyRecord(
                        vbeln=vbeln,
                        posnr=posnr,
                        category=DiscrepancyCategory.MISSING_IN_CMM_VLOGP,
                        vbap_attributes=vbap_attrs,
                        qrf_research=self._research_qrfc_cached(
                            vbeln, posnr, qin, err, qrfc_cache
                        ),
                    )
                )
                continue

            # Category 2 — join uses latest/direct match; attribute compare uses first snapshot.
            compare_pool = _cmm_rows_for_match_key(cmm, vbeln, posnr, match_path or "")
            compare_row = _select_cmm_compare_row(compare_pool, cmm_row)
            mismatched = self._compare_attributes(row, compare_row)

            if mismatched:
                cmm_attrs = {col: _norm(compare_row.get(col)) for col in compare_row.index}
                results.append(
                    DiscrepancyRecord(
                        vbeln=vbeln,
                        posnr=posnr,
                        category=DiscrepancyCategory.ATTRIBUTE_MISMATCH,
                        vbap_attributes=vbap_attrs,
                        cmm_attributes=cmm_attrs,
                        cmm_match_path=match_path,
                        vbap_line_fields=_extract_vbap_line_fields(row),
                        mismatched_fields=mismatched,
                        change_history=self._research_changes_cached(
                            vbeln,
                            posnr,
                            cdhdr,
                            cdpos,
                            change_index,
                            change_cache,
                            cmm=cmm,
                            cmm_row=cmm_row,
                            mandt=_norm(row.get("MANDT")),
                        ),
                    )
                )

        return results

    def _compare_attributes(self, vbap_row: pd.Series, cmm_row: pd.Series) -> list[str]:
        mismatched: list[str] = []
        for vbap_field, cmm_field in self.compare_attributes:
            if vbap_field not in vbap_row.index:
                mismatched.append(f"{vbap_field}/{cmm_field}: missing VBAP column '{vbap_field}'")
                continue
            if cmm_field not in cmm_row.index:
                mismatched.append(f"{vbap_field}/{cmm_field}: missing CMM column '{cmm_field}'")
                continue
            vbap_val = _norm(vbap_row.get(vbap_field, ""))
            cmm_val = _norm(cmm_row.get(cmm_field, ""))
            if vbap_val == "" and cmm_val == "":
                continue
            if not values_equal(vbap_val, cmm_val):
                mismatched.append(f"{vbap_field}/{cmm_field}: {vbap_val} != {cmm_val}")
        return mismatched

    def _research_qrfc_cached(
        self,
        vbeln: str,
        posnr: str,
        qin: pd.DataFrame,
        err: pd.DataFrame,
        cache: Dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        key = f"{canonical_document_key(vbeln)}:{canonical_item_key(posnr)}"
        if key in cache:
            return cache[key]
        result = self._research_qrfc(vbeln, posnr, qin, err)
        cache[key] = result
        return result

    def _enrich_qrfc_match(self, entry: dict[str, Any]) -> dict[str, Any]:
        err = entry.get("error") if isinstance(entry.get("error"), dict) else {}
        merged = {**err, **entry}
        message_id, message_number, raw_message = extract_qrfc_err_state_fields(merged)
        resolved = resolve_finetuning_from_qrfc_err(merged)
        if resolved["match_type"] != "none":
            entry["finetuning"] = {
                "message_id": message_id,
                "message_number": message_number,
                **resolved,
            }
        else:
            entry["finetuning"] = None
        entry["MESSAGE_ID"] = message_id
        entry["MESSAGE_NUMBER"] = message_number
        entry["MESSAGE"] = raw_message
        entry["message_id"] = message_id
        entry["message_number"] = message_number
        entry["message"] = raw_message
        entry["standard_system_text"] = resolved["standard_system_text"]
        entry["sap_component_area"] = resolved["sap_component_area"]
        entry["diagnostic_tcode"] = resolved["diagnostic_tcode"]
        return entry

    def _research_qrfc(
        self, vbeln: str, posnr: str, qin: pd.DataFrame, err: pd.DataFrame
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"queue_matches": [], "errors": []}

        if qin.empty:
            return result

        pattern = canonical_document_key(vbeln).lower()
        if not pattern:
            return result

        matches = qin[
            qin["QUEUE_NAME"].astype(str).str.lower().str.contains(pattern, na=False)
        ]

        err_by_unit: Dict[str, pd.DataFrame] = {}
        if not err.empty and "UNIT_ID" in err.columns:
            unit_ids = err["UNIT_ID"].astype(str).str.strip()
            for unit_id, group in err.groupby(unit_ids, sort=False):
                if unit_id:
                    err_by_unit[unit_id] = group

        for _, qrow in matches.iterrows():
            unit_id = _norm(qrow.get("UNIT_ID"))
            queue_name = _norm(qrow.get("QUEUE_NAME"))
            if err_by_unit and unit_id:
                err_rows = err_by_unit.get(unit_id, pd.DataFrame())
                if err_rows.empty:
                    result["queue_matches"].append(
                        self._enrich_qrfc_match(
                            {
                                "queue_name": queue_name,
                                "unit_id": unit_id,
                                "message": "",
                                "message_id": "",
                                "message_number": "",
                            }
                        )
                    )
                    continue
                for _, erow in err_rows.iterrows():
                    message_id, message_number, message = extract_qrfc_err_state_fields(erow)
                    match_entry = {
                        "queue_name": queue_name,
                        "unit_id": unit_id,
                        "MESSAGE": message,
                        "MESSAGE_ID": message_id,
                        "MESSAGE_NUMBER": message_number,
                        "message": message,
                        "message_id": message_id,
                        "message_number": message_number,
                        "error": {
                            "MESSAGE": message,
                            "MESSAGE_ID": message_id,
                            "MESSAGE_NUMBER": message_number,
                            "message": message,
                            "message_id": message_id,
                            "message_number": message_number,
                        },
                    }
                    result["queue_matches"].append(self._enrich_qrfc_match(match_entry))
                    result["errors"].append(
                        {
                            "message": message,
                            "message_id": message_id,
                            "message_number": message_number,
                        }
                    )
            else:
                result["queue_matches"].append(
                    self._enrich_qrfc_match(
                        {
                            "queue_name": queue_name,
                            "unit_id": unit_id,
                            "message": "",
                            "message_id": "",
                            "message_number": "",
                        }
                    )
                )

        return result

    def _research_changes_cached(
        self,
        vbeln: str,
        posnr: str,
        cdhdr: pd.DataFrame,
        cdpos: pd.DataFrame,
        index: ChangeResearchIndex,
        cache: Dict[str, list[dict[str, Any]]],
        *,
        cmm: pd.DataFrame,
        cmm_row: pd.Series,
        mandt: str = "",
    ) -> list[dict[str, Any]]:
        key = f"{canonical_document_key(vbeln)}:{canonical_item_key(posnr)}"
        if key not in cache:
            cache[key] = research_vbep_changes_for_vbeln(
                vbeln,
                cdhdr,
                cdpos,
                posnr=posnr,
                index=index,
                cmm=cmm,
                cmm_row=cmm_row,
                mandt=mandt,
            )
        return list(cache[key])

    def count_commodity_relevant(self) -> int:
        return len(self._scoped_commodity())
