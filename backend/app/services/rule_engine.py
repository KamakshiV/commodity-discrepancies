from typing import Any, List, Optional

import pandas as pd

from app.models.schemas import DiscrepancyCategory, DiscrepancyRecord
from app.services.data_loader import (
    COMMODITY_FILTER_COLUMN,
    DEFAULT_COMPARE_MAPPINGS,
    DataStore,
    filter_vbap_scope,
    mappings_to_tuples,
)
from app.services.change_document_research import research_vbep_changes_for_vbeln
from app.services.field_compare import canonical_document_key, norm, sap_keys_match, values_equal


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


class RuleEngine:
    """Deterministic discrepancy detection — AI must not override these results."""

    def __init__(
        self,
        store: DataStore,
        compare_mappings: list = None,
        scope_vbelns: Optional[List[str]] = None,
        scope_erdat: Optional[str] = None,
    ):
        self.store = store
        raw = compare_mappings if compare_mappings is not None else DEFAULT_COMPARE_MAPPINGS
        self.compare_attributes = mappings_to_tuples(raw)
        self.scope_vbelns = scope_vbelns
        self.scope_erdat = scope_erdat

    def _scoped_commodity(self) -> pd.DataFrame:
        vbap = self.store.get("VBAP")
        if vbap.empty:
            return vbap
        return filter_vbap_scope(
            vbap,
            vbelns=self.scope_vbelns if self.scope_vbelns else None,
            erdat=self.scope_erdat,
        )

    def run(self) -> list[DiscrepancyRecord]:
        vbap = self.store.get("VBAP")
        cmm = self.store.get("CMM_VLOGP")

        if vbap.empty:
            return []

        commodity = self._scoped_commodity()
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
                        vbap_line_fields=_extract_vbap_line_fields(row),
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
            queue_name = _norm(qrow.get("QUEUE_NAME"))
            if not err.empty and unit_id:
                err_rows = err[err["UNIT_ID"].astype(str).str.strip() == unit_id]
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

    def _research_changes(self, vbeln: str, posnr: str) -> list[dict[str, Any]]:
        """Scenario 2: CDHDR (by VBELN→OBJECTID) → CDPOS join, TABNAME=VBEP."""
        return research_vbep_changes_for_vbeln(
            vbeln,
            self.store.get("CDHDR"),
            self.store.get("CDPOS"),
            posnr=posnr,
        )

    def count_commodity_relevant(self) -> int:
        return len(self._scoped_commodity())
