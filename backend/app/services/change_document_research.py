"""
Scenario 2 — Attribute mismatch change document research (CDHDR → CDPOS).

For a VBAP line (VBELN + POSNR) with attribute differences vs CMM_VLOGP:
1. Match VBAP.VBELN to CDHDR.OBJECTID
2. From CDHDR take CHANGENR, OBJECTID, OBJECTCLASS (or SAP alias OBJECTCLAS)
3. Join CDPOS on CHANGENR + OBJECTCLASS
4. Return all matching CDPOS rows (all TABNAME values)
5. Return TABNAME, FNAME, VALUE_NEW, VALUE_OLD plus CDHDR keys
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.services.field_compare import canonical_document_key, norm

OBJECTCLASS_COLUMNS = ("OBJECTCLASS", "OBJECTCLAS")


def _resolve_column(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    for name in candidates:
        if name in df.columns:
            return name
    return None


def _empty_cdhdr() -> pd.DataFrame:
    return pd.DataFrame()


@dataclass
class ChangeResearchIndex:
    """Pre-indexed CDHDR/CDPOS for fast per-VBELN change lookups."""

    cdhdr_by_vbeln: Dict[str, pd.DataFrame] = field(default_factory=dict)
    cdpos_by_header: Dict[Tuple[str, str], pd.DataFrame] = field(default_factory=dict)
    oc_pos_col: Optional[str] = None
    has_required_cdpos_cols: bool = False

    @classmethod
    def build(cls, cdhdr: pd.DataFrame, cdpos: pd.DataFrame) -> "ChangeResearchIndex":
        index = cls()
        if cdhdr.empty or "OBJECTID" not in cdhdr.columns:
            pass
        else:
            keys = cdhdr["OBJECTID"].map(canonical_document_key)
            for vbeln_key in keys.unique():
                if not vbeln_key:
                    continue
                matched = cdhdr[keys == vbeln_key]
                if not matched.empty:
                    index.cdhdr_by_vbeln[vbeln_key] = matched

        if cdpos.empty:
            return index

        required_pos = {"CHANGENR", "OBJECTID", "TABNAME", "FNAME", "VALUE_NEW", "VALUE_OLD"}
        index.has_required_cdpos_cols = required_pos.issubset(cdpos.columns)
        oc_pos_col = _resolve_column(cdpos, *OBJECTCLASS_COLUMNS)
        index.oc_pos_col = oc_pos_col
        if not oc_pos_col or "CHANGENR" not in cdpos.columns:
            return index

        cnr = cdpos["CHANGENR"].astype(str).str.strip()
        oc = cdpos[oc_pos_col].astype(str).str.strip()
        for (changenr, objectclass), group in cdpos.groupby([cnr, oc], sort=False):
            if changenr and objectclass:
                index.cdpos_by_header[(changenr, objectclass)] = group

        return index


def _match_cdhdr_by_vbeln(cdhdr: pd.DataFrame, vbeln: str) -> pd.DataFrame:
    """CDHDR rows where OBJECTID corresponds to VBAP.VBELN (leading-zero tolerant)."""
    if cdhdr.empty or "OBJECTID" not in cdhdr.columns:
        return _empty_cdhdr()

    target = canonical_document_key(vbeln)
    if not target:
        return _empty_cdhdr()

    keys = cdhdr["OBJECTID"].map(canonical_document_key)
    exact = cdhdr[keys == target]
    if not exact.empty:
        return exact.copy()

    return cdhdr[cdhdr["OBJECTID"].astype(str).str.strip() == norm(vbeln)].copy()


def _cdpos_for_cdhdr_header(
    cdpos: pd.DataFrame,
    changenr: str,
    objectclass: str,
    oc_pos_col: str,
) -> pd.DataFrame:
    """Join CDPOS to a CDHDR header row (full scan — prefer ChangeResearchIndex)."""
    if cdpos.empty:
        return cdpos.iloc[0:0]

    base = cdpos[
        (cdpos["CHANGENR"].astype(str).str.strip() == changenr)
        & (cdpos[oc_pos_col].astype(str).str.strip() == objectclass)
    ]
    return base


def research_vbep_changes_for_vbeln(
    vbeln: str,
    cdhdr: pd.DataFrame,
    cdpos: pd.DataFrame,
    *,
    posnr: Optional[str] = None,
    index: Optional[ChangeResearchIndex] = None,
) -> List[Dict[str, Any]]:
    """
    Run Scenario 2 change-document research for one sales order item.

    Pass a shared ``ChangeResearchIndex`` when processing many VBAP lines.
  """
    if index is None:
        index = ChangeResearchIndex.build(cdhdr, cdpos)

    target = canonical_document_key(vbeln)
    headers = index.cdhdr_by_vbeln.get(target, _empty_cdhdr())
    if headers.empty:
        headers = _match_cdhdr_by_vbeln(cdhdr, vbeln)
    if headers.empty or cdpos.empty or not index.has_required_cdpos_cols:
        return []

    oc_hdr_col = _resolve_column(headers, *OBJECTCLASS_COLUMNS)
    if not oc_hdr_col or not index.oc_pos_col:
        return []

    changes: List[Dict[str, Any]] = []
    for _, hrow in headers.iterrows():
        changenr = norm(hrow.get("CHANGENR"))
        objectclass = norm(hrow.get(oc_hdr_col))
        if not changenr or not objectclass:
            continue

        positions = index.cdpos_by_header.get((changenr, objectclass))
        if positions is None:
            positions = _cdpos_for_cdhdr_header(
                cdpos, changenr, objectclass, index.oc_pos_col
            )

        for _, prow in positions.iterrows():
            objectid = norm(hrow.get("OBJECTID"))
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
