"""
Scenario 2 — Attribute mismatch change document research (CDHDR → CDPOS).

For a VBAP line (VBELN + POSNR) with attribute differences vs CMM_VLOGP:
1. Match VBAP.VBELN to CDHDR.OBJECTID
2. From CDHDR take CHANGENR, OBJECTID, OBJECTCLASS (or SAP alias OBJECTCLAS)
3. Join CDPOS on CHANGENR, OBJECTID, OBJECTCLASS
4. Keep CDPOS rows where TABNAME = 'VBEP'
5. Return TABNAME, FNAME, VALUE_NEW, VALUE_OLD plus CDHDR keys
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from app.services.field_compare import canonical_document_key, norm

OBJECTCLASS_COLUMNS = ("OBJECTCLASS", "OBJECTCLAS")
VBEP_TABNAME = "VBEP"


def _resolve_column(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    for name in candidates:
        if name in df.columns:
            return name
    return None


def _objectclass_series(df: pd.DataFrame) -> Optional[pd.Series]:
    col = _resolve_column(df, *OBJECTCLASS_COLUMNS)
    if not col:
        return None
    return df[col].astype(str).str.strip()


def _match_cdhdr_by_vbeln(cdhdr: pd.DataFrame, vbeln: str) -> pd.DataFrame:
    """CDHDR rows where OBJECTID corresponds to VBAP.VBELN (leading-zero tolerant)."""
    if cdhdr.empty or "OBJECTID" not in cdhdr.columns:
        return cdhdr.iloc[0:0]

    target = canonical_document_key(vbeln)
    if not target:
        return cdhdr.iloc[0:0]

    object_ids = cdhdr["OBJECTID"].astype(str).str.strip()
    mask = object_ids.apply(lambda oid: canonical_document_key(oid) == target)
    return cdhdr[mask].copy()


def research_vbep_changes_for_vbeln(
    vbeln: str,
    cdhdr: pd.DataFrame,
    cdpos: pd.DataFrame,
    *,
    posnr: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Run Scenario 2 change-document research for one sales order item.

    posnr is recorded on each change row for traceability; CDPOS filtering uses TABNAME=VBEP
    per specification (not POSNR on TABKEY).
    """
    changes: List[Dict[str, Any]] = []
    headers = _match_cdhdr_by_vbeln(cdhdr, vbeln)
    if headers.empty or cdpos.empty:
        return changes

    oc_hdr_col = _resolve_column(headers, *OBJECTCLASS_COLUMNS)
    oc_pos_col = _resolve_column(cdpos, *OBJECTCLASS_COLUMNS)
    if not oc_hdr_col or not oc_pos_col:
        return changes

    required_pos = {"CHANGENR", "OBJECTID", "TABNAME", "FNAME", "VALUE_NEW", "VALUE_OLD"}
    if not required_pos.issubset(cdpos.columns):
        return changes

    pos_objectclass = cdpos[oc_pos_col].astype(str).str.strip()

    for _, hrow in headers.iterrows():
        changenr = norm(hrow.get("CHANGENR"))
        objectid = norm(hrow.get("OBJECTID"))
        objectclass = norm(hrow.get(oc_hdr_col))

        if not changenr or not objectid or not objectclass:
            continue

        positions = cdpos[
            (cdpos["CHANGENR"].astype(str).str.strip() == changenr)
            & (cdpos["OBJECTID"].astype(str).str.strip() == objectid)
            & (pos_objectclass == objectclass)
            & (cdpos["TABNAME"].astype(str).str.strip().str.upper() == VBEP_TABNAME)
        ]

        for _, prow in positions.iterrows():
            entry: Dict[str, Any] = {
                "CHANGENR": changenr,
                "OBJECTID": objectid,
                "OBJECTCLASS": objectclass,
                "TABNAME": norm(prow.get("TABNAME")),
                "FNAME": norm(prow.get("FNAME")),
                "VALUE_OLD": norm(prow.get("VALUE_OLD")),
                "VALUE_NEW": norm(prow.get("VALUE_NEW")),
            }
            if posnr:
                entry["POSNR"] = norm(posnr)
            changes.append(entry)

    return changes
