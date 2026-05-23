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


def _build_cmm_index(cmm: pd.DataFrame) -> Dict[Tuple[str, str], pd.Series]:
    """Map (document_key, item_key) → first matching CMM_VLOGP row."""
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
        if key[0] and key not in index:
            index[key] = row
    return index


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

            cmm_row = cmm_index.get(
                (canonical_document_key(vbeln), canonical_item_key(posnr))
            )

            if cmm_row is None:
                results.append(
                    DiscrepancyRecord(
                        vbeln=vbeln,
                        posnr=posnr,
                        category=DiscrepancyCategory.MISSING_IN_CMM_VLOGP,
                        vbap_attributes=vbap_attrs,
                        qrf_research=self._research_qrfc_cached(
                            vbeln, qin, err, qrfc_cache
                        ),
                    )
                )
                continue

            cmm_attrs = {col: _norm(cmm_row.get(col)) for col in cmm_row.index}
            mismatched = self._compare_attributes(row, cmm_row)

            if mismatched:
                results.append(
                    DiscrepancyRecord(
                        vbeln=vbeln,
                        posnr=posnr,
                        category=DiscrepancyCategory.ATTRIBUTE_MISMATCH,
                        vbap_attributes=vbap_attrs,
                        cmm_attributes=cmm_attrs,
                        vbap_line_fields=_extract_vbap_line_fields(row),
                        mismatched_fields=mismatched,
                        change_history=self._research_changes_cached(
                            vbeln,
                            posnr,
                            cdhdr,
                            cdpos,
                            change_index,
                            change_cache,
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
        qin: pd.DataFrame,
        err: pd.DataFrame,
        cache: Dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        key = canonical_document_key(vbeln)
        if key in cache:
            return cache[key]
        result = self._research_qrfc(vbeln, qin, err)
        cache[key] = result
        return result

    def _research_qrfc(
        self, vbeln: str, qin: pd.DataFrame, err: pd.DataFrame
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
                        {
                            "queue_name": queue_name,
                            "unit_id": unit_id,
                            "message": "",
                            "message_id": "",
                        }
                    )
                    continue
                for _, erow in err_rows.iterrows():
                    message = _norm(erow.get("MESSAGE"))
                    message_id = _norm(erow.get("MESSAGE_ID"))
                    result["queue_matches"].append(
                        {
                            "queue_name": queue_name,
                            "unit_id": unit_id,
                            "message": message,
                            "message_id": message_id,
                            "error": {"message": message, "message_id": message_id},
                        }
                    )
                    result["errors"].append(
                        {"message": message, "message_id": message_id}
                    )
            else:
                result["queue_matches"].append(
                    {
                        "queue_name": queue_name,
                        "unit_id": unit_id,
                        "message": "",
                        "message_id": "",
                    }
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
    ) -> list[dict[str, Any]]:
        key = canonical_document_key(vbeln)
        if key not in cache:
            cache[key] = research_vbep_changes_for_vbeln(
                vbeln,
                cdhdr,
                cdpos,
                index=index,
            )
        base = cache[key]
        if not posnr:
            return list(base)
        return [{**entry, "POSNR": norm(posnr)} for entry in base]

    def count_commodity_relevant(self) -> int:
        return len(self._scoped_commodity())
