from typing import Any

import pandas as pd

from app.models.schemas import DiscrepancyCategory, DiscrepancyRecord
from app.services.data_loader import (
    COMMODITY_FILTER_COLUMN,
    DEFAULT_COMPARE_MAPPINGS,
    DataStore,
    count_commodity_relevant,
    filter_commodity_relevant,
    mappings_to_tuples,
)
from app.services.change_document_research import research_vbep_changes_for_vbeln
from app.services.field_compare import canonical_document_key, norm, sap_keys_match, values_equal


def _norm(val: Any) -> str:
    """Backward-compatible alias."""
    return norm(val)


class RuleEngine:
    """Deterministic discrepancy detection — AI must not override these results."""

    def __init__(self, store: DataStore, compare_mappings: list = None):
        self.store = store
        raw = compare_mappings if compare_mappings is not None else DEFAULT_COMPARE_MAPPINGS
        self.compare_attributes = mappings_to_tuples(raw)

    def run(self) -> list[DiscrepancyRecord]:
        vbap = self.store.get("VBAP")
        cmm = self.store.get("CMM_VLOGP")

        if vbap.empty:
            return []

        commodity = filter_commodity_relevant(vbap)
        results: list[DiscrepancyRecord] = []
        join_exclude = {"VBELN", "POSNR", COMMODITY_FILTER_COLUMN}

        for _, row in commodity.iterrows():
            vbeln = _norm(row.get("VBELN"))
            posnr = _norm(row.get("POSNR"))
            vbap_attrs = {
                col: _norm(row.get(col))
                for col in row.index
                if col not in join_exclude
            }

            cmm_matches = pd.DataFrame()
            if not cmm.empty:
                match_mask = cmm.apply(
                    lambda r: sap_keys_match(
                        vbeln,
                        r.get("DOCUMENT_CHAR10"),
                        posnr,
                        r.get("DOCUMENT_ITEM"),
                    ),
                    axis=1,
                )
                cmm_matches = cmm[match_mask]

            if cmm_matches.empty:
                results.append(
                    DiscrepancyRecord(
                        vbeln=vbeln,
                        posnr=posnr,
                        category=DiscrepancyCategory.MISSING_IN_CMM_VLOGP,
                        vbap_attributes=vbap_attrs,
                        qrf_research=self._research_qrfc(vbeln),
                    )
                )
                continue

            cmm_row = cmm_matches.iloc[0]
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
                        mismatched_fields=mismatched,
                        change_history=self._research_changes(vbeln, posnr),
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

    def _research_qrfc(self, vbeln: str) -> dict[str, Any]:
        qin = self.store.get("QRFC_I_QIN_TOP")
        err = self.store.get("QRFC_I_ERR_STATE")
        result: dict[str, Any] = {"queue_matches": [], "errors": []}

        if qin.empty:
            return result

        pattern = canonical_document_key(vbeln).lower()
        if not pattern:
            return result
        matches = qin[
            qin["QUEUE_NAME"].astype(str).str.lower().str.contains(pattern, na=False)
        ]
        for _, qrow in matches.iterrows():
            unit_id = _norm(qrow.get("UNIT_ID"))
            entry = {
                "queue_name": _norm(qrow.get("QUEUE_NAME")),
                "unit_id": unit_id,
            }
            if not err.empty and unit_id:
                err_rows = err[err["UNIT_ID"].astype(str).str.strip() == unit_id]
                for _, erow in err_rows.iterrows():
                    entry["error"] = {
                        "message": _norm(erow.get("MESSAGE")),
                        "message_id": _norm(erow.get("MESSAGE_ID")),
                    }
                    result["errors"].append(entry["error"])
            result["queue_matches"].append(entry)

        return result

    def _research_changes(self, vbeln: str, posnr: str) -> list[dict[str, Any]]:
        """Scenario 2: CDHDR (by VBELN→OBJECTID) → CDPOS join, TABNAME=VBEP."""
        return research_vbep_changes_for_vbeln(
            vbeln,
            self.store.get("CDHDR"),
            self.store.get("CDPOS"),
            posnr=posnr,
        )

    def count_commodity_relevant(self) -> int:
        vbap = self.store.get("VBAP")
        return count_commodity_relevant(vbap)
