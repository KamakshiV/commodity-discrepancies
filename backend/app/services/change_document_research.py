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
    exact = cdhdr[mask].copy()
    if not exact.empty:
        return exact

    # Fallback: exact string match after strip (non-numeric OBJECTID values)
    return cdhdr[object_ids == norm(vbeln)].copy()


def _cdpos_for_cdhdr_header(
    cdpos: pd.DataFrame,
    changenr: str,
    objectclass: str,
    oc_pos_col: str,
    *,
    include_vbap_fallback: bool = True,
) -> pd.DataFrame:
    """
    Join CDPOS to a CDHDR header row.

    SAP often stores VBELN in CDHDR.OBJECTID but an internal object id in
    CDPOS.OBJECTID for the same CHANGENR. Join on CHANGENR + OBJECTCLASS only.
    Prefer TABNAME=VBEP; include VBAP when no VBEP lines exist (common for
    VBAP attribute changes in customer extracts).
    """
    if cdpos.empty:
        return cdpos.iloc[0:0]

    base = cdpos[
        (cdpos["CHANGENR"].astype(str).str.strip() == changenr)
        & (cdpos[oc_pos_col].astype(str).str.strip() == objectclass)
    ]
    if base.empty:
        return base

    tab = base["TABNAME"].astype(str).str.strip().str.upper()
    vbep = base[tab == VBEP_TABNAME]
    if not vbep.empty:
        return vbep

    if include_vbap_fallback:
        vbap = base[tab == "VBAP"]
        if not vbap.empty:
            return vbap

    return base.iloc[0:0]


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

    for _, hrow in headers.iterrows():
        changenr = norm(hrow.get("CHANGENR"))
        objectid = norm(hrow.get("OBJECTID"))
        objectclass = norm(hrow.get(oc_hdr_col))

        if not changenr or not objectid or not objectclass:
            continue

        positions = _cdpos_for_cdhdr_header(
            cdpos,
            changenr,
            objectclass,
            oc_pos_col,
        )

        for _, prow in positions.iterrows():
            entry: Dict[str, Any] = {
                "CHANGENR": changenr,
                "OBJECTID": norm(prow.get("OBJECTID")) or objectid,
                "OBJECTCLASS": objectclass,
                "CDHDR_OBJECTID": objectid,
                "CDPOS_OBJECTID": norm(prow.get("OBJECTID")),
                "TABNAME": norm(prow.get("TABNAME")),
                "FNAME": norm(prow.get("FNAME")),
                "VALUE_OLD": norm(prow.get("VALUE_OLD")),
                "VALUE_NEW": norm(prow.get("VALUE_NEW")),
            }
            if posnr:
                entry["POSNR"] = norm(posnr)
            changes.append(entry)

    return changes
