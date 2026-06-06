"""
Scenario 2 — Attribute mismatch change document research (CDHDR → CDPOS).

For a VBAP line (VBELN + POSNR) with attribute differences vs CMM_VLOGP:
1. Match VBAP.VBELN to CDHDR.OBJECTID
2. From CDHDR take CHANGENR, OBJECTID, OBJECTCLASS (or SAP alias OBJECTCLAS)
3. Join CDPOS on CHANGENR + OBJECTID + OBJECTCLASS; if no rows, fall back to
   CHANGENR + OBJECTCLASS (CDPOS.OBJECTID may differ from CDHDR.OBJECTID)
4. Keep CDPOS rows where TABNAME = 'VBEP'
5. Return TABNAME, FNAME, VALUE_NEW, VALUE_OLD plus CDHDR keys
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.services.field_compare import canonical_document_key, canonical_item_key, norm

OBJECTCLASS_COLUMNS = ("OBJECTCLASS", "OBJECTCLAS")
VBEP_TABNAME = "VBEP"


def _resolve_column(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    for name in candidates:
        if name in df.columns:
            return name
    return None


def _empty_cdhdr() -> pd.DataFrame:
    return pd.DataFrame()


def _is_vbep_tabname(tabname: Any) -> bool:
    return norm(tabname).upper() == VBEP_TABNAME


def _tabkey_matches_posnr(tabkey: Any, posnr: str) -> bool:
    """Best-effort item filter when CDPOS.TABKEY embeds the schedule line number."""
    if not posnr or not norm(posnr):
        return True
    tk = norm(tabkey)
    if not tk:
        return True
    item = canonical_item_key(posnr)
    padded = posnr.strip()
    return (
        tk.endswith(item)
        or tk.endswith(padded)
        or (len(item) >= 4 and item in tk)
    )


def _filter_vbep_rows(positions: pd.DataFrame) -> pd.DataFrame:
    if positions.empty or "TABNAME" not in positions.columns:
        return positions.iloc[0:0]
    mask = positions["TABNAME"].map(_is_vbep_tabname)
    return positions[mask].copy()


def resolve_cdhdr_object_candidates(
    vbeln: str,
    posnr: str,
    cmm: pd.DataFrame,
    cmm_row: Optional[pd.Series] = None,
) -> List[str]:
    """
    OBJECTID keys to try in CDHDR.

    SAP exports often store internal document numbers in CDHDR/CDPOS while VBAP
    carries VBELN. When direct VBELN match fails, derive internal ids from the
    matched CMM row and from ROOT_DOC / PREDECESSOR_DOC siblings.
    """
    candidates: List[str] = []
    seen: set[str] = set()

    def add(val: Any) -> None:
        for key in (canonical_document_key(val), norm(val)):
            if key and key not in seen:
                seen.add(key)
                candidates.append(key)

    add(vbeln)

    if cmm_row is not None:
        for col in ("DOCUMENT_CHAR10", "DOCUMENT", "ROOT_DOC", "PREDECESSOR_DOC"):
            if col in cmm_row.index:
                add(cmm_row.get(col))

    if cmm.empty or not norm(vbeln):
        return candidates

    v_key = canonical_document_key(vbeln)
    p_key = canonical_item_key(posnr) if norm(posnr) else ""

    for link_col in ("ROOT_DOC", "PREDECESSOR_DOC", "DOCUMENT_CHAR10"):
        if link_col not in cmm.columns:
            continue
        link_keys = cmm[link_col].map(canonical_document_key)
        linked = cmm[link_keys == v_key]
        if p_key and "DOCUMENT_ITEM" in linked.columns:
            item_keys = linked["DOCUMENT_ITEM"].map(canonical_item_key)
            item_match = linked[item_keys == p_key]
            if not item_match.empty:
                linked = item_match
        for _, crow in linked.iterrows():
            for col in ("DOCUMENT_CHAR10", "DOCUMENT"):
                if col in crow.index:
                    add(crow.get(col))

    return candidates


def _headers_for_object_key(
    cdhdr: pd.DataFrame,
    index: ChangeResearchIndex,
    object_key: str,
) -> pd.DataFrame:
    if not object_key:
        return _empty_cdhdr()
    headers = index.cdhdr_by_vbeln.get(object_key, _empty_cdhdr())
    if not headers.empty:
        return headers
    if cdhdr.empty or "OBJECTID" not in cdhdr.columns:
        return _empty_cdhdr()
    keys = cdhdr["OBJECTID"].map(canonical_document_key)
    matched = cdhdr[keys == object_key]
    if not matched.empty:
        return matched.copy()
    return cdhdr[cdhdr["OBJECTID"].astype(str).str.strip() == object_key].copy()


def _cdpos_tabkey_candidates(mandt: str, object_id: str, posnr: str) -> List[str]:
    """Build SAP-style CDPOS.TABKEY values (MANDT + doc id + item)."""
    m = norm(mandt)
    pos = norm(posnr)
    oid = norm(object_id)
    if not m or not oid or not pos:
        return []
    keys: List[str] = []
    seen: set[str] = set()
    for doc in (oid, oid.lstrip("0") or oid, canonical_document_key(oid)):
        if not doc:
            continue
        key = f"{m}{doc}{pos}"
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def _cdpos_direct_by_tabkey(
    cdpos: pd.DataFrame,
    mandt: str,
    object_candidates: List[str],
    posnr: str,
) -> pd.DataFrame:
    """Fallback: locate CDPOS rows by TABKEY when CDHDR.OBJECTID is not VBELN."""
    if cdpos.empty or "TABKEY" not in cdpos.columns or not index_has_required_cdpos(cdpos):
        return cdpos.iloc[0:0]

    tabkeys: set[str] = set()
    for obj in object_candidates:
        tabkeys.update(_cdpos_tabkey_candidates(mandt, obj, posnr))
    if not tabkeys:
        return cdpos.iloc[0:0]

    matched = cdpos[cdpos["TABKEY"].astype(str).str.strip().isin(tabkeys)]
    return _filter_vbep_rows(matched)


def index_has_required_cdpos(cdpos: pd.DataFrame) -> bool:
    required = {"CHANGENR", "OBJECTID", "TABNAME", "FNAME", "VALUE_NEW", "VALUE_OLD"}
    return required.issubset(cdpos.columns)


def _filter_posnr_rows(positions: pd.DataFrame, posnr: Optional[str]) -> pd.DataFrame:
    if positions.empty or not posnr or "TABKEY" not in positions.columns:
        return positions
    matched = positions[
        positions["TABKEY"].apply(lambda val: _tabkey_matches_posnr(val, posnr))
    ]
    return matched if not matched.empty else positions


@dataclass
class ChangeResearchIndex:
    """Pre-indexed CDHDR/CDPOS for fast per-VBELN change lookups."""

    cdhdr_by_vbeln: Dict[str, pd.DataFrame] = field(default_factory=dict)
    cdpos_by_header: Dict[Tuple[str, str], pd.DataFrame] = field(default_factory=dict)
    cdpos_by_full_header: Dict[Tuple[str, str, str], pd.DataFrame] = field(
        default_factory=dict
    )
    oc_pos_col: Optional[str] = None
    has_required_cdpos_cols: bool = False

    @classmethod
    def build(cls, cdhdr: pd.DataFrame, cdpos: pd.DataFrame) -> "ChangeResearchIndex":
        index = cls()
        if not cdhdr.empty and "OBJECTID" in cdhdr.columns:
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
        oid_keys = cdpos["OBJECTID"].map(canonical_document_key)

        for (changenr, objectclass), group in cdpos.groupby([cnr, oc], sort=False):
            if changenr and objectclass:
                index.cdpos_by_header[(changenr, objectclass)] = group

        for (changenr, oid_key, objectclass), group in cdpos.groupby(
            [cnr, oid_keys, oc], sort=False
        ):
            if changenr and oid_key and objectclass:
                index.cdpos_by_full_header[(changenr, oid_key, objectclass)] = group

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
    *,
    hdr_objectid: str = "",
) -> pd.DataFrame:
    """Join CDPOS to CDHDR — 3-key first, then CHANGENR + OBJECTCLASS fallback."""
    if cdpos.empty:
        return cdpos.iloc[0:0]

    hdr_oid_key = canonical_document_key(hdr_objectid)
    if hdr_oid_key:
        three_key = cdpos[
            (cdpos["CHANGENR"].astype(str).str.strip() == changenr)
            & (cdpos[oc_pos_col].astype(str).str.strip() == objectclass)
            & (cdpos["OBJECTID"].map(canonical_document_key) == hdr_oid_key)
        ]
        if not three_key.empty:
            return three_key

    return cdpos[
        (cdpos["CHANGENR"].astype(str).str.strip() == changenr)
        & (cdpos[oc_pos_col].astype(str).str.strip() == objectclass)
    ]


def _lookup_cdpos_for_header(
    hrow: pd.Series,
    oc_hdr_col: str,
    cdpos: pd.DataFrame,
    index: ChangeResearchIndex,
) -> pd.DataFrame:
    changenr = norm(hrow.get("CHANGENR"))
    objectclass = norm(hrow.get(oc_hdr_col))
    hdr_objectid = norm(hrow.get("OBJECTID"))
    hdr_oid_key = canonical_document_key(hdr_objectid)
    if not changenr or not objectclass or not index.oc_pos_col:
        return cdpos.iloc[0:0]

    positions: Optional[pd.DataFrame] = None
    if hdr_oid_key:
        positions = index.cdpos_by_full_header.get((changenr, hdr_oid_key, objectclass))

    if positions is None or positions.empty:
        positions = index.cdpos_by_header.get((changenr, objectclass))

    if positions is None or positions.empty:
        positions = _cdpos_for_cdhdr_header(
            cdpos,
            changenr,
            objectclass,
            index.oc_pos_col,
            hdr_objectid=hdr_objectid,
        )

    return positions if positions is not None else cdpos.iloc[0:0]


def _change_entry_dedupe_key(entry: Dict[str, Any]) -> tuple[str, ...]:
    return (
        norm(entry.get("CHANGENR")),
        norm(entry.get("CDHDR_OBJECTID")),
        norm(entry.get("TABNAME")),
        norm(entry.get("FNAME")),
        norm(entry.get("VALUE_OLD")),
        norm(entry.get("VALUE_NEW")),
    )


def _collect_changes_from_headers(
    headers: pd.DataFrame,
    cdpos: pd.DataFrame,
    index: ChangeResearchIndex,
    posnr: Optional[str],
    changes: List[Dict[str, Any]],
    seen: set[tuple[str, ...]],
) -> None:
    oc_hdr_col = _resolve_column(headers, *OBJECTCLASS_COLUMNS)
    if not oc_hdr_col or not index.oc_pos_col:
        return

    for _, hrow in headers.iterrows():
        positions = _lookup_cdpos_for_header(hrow, oc_hdr_col, cdpos, index)
        positions = _filter_vbep_rows(positions)
        positions = _filter_posnr_rows(positions, posnr)

        changenr = norm(hrow.get("CHANGENR"))
        objectclass = norm(hrow.get(oc_hdr_col))
        hdr_objectid = norm(hrow.get("OBJECTID"))

        for _, prow in positions.iterrows():
            entry: Dict[str, Any] = {
                "CHANGENR": changenr,
                "OBJECTID": norm(prow.get("OBJECTID")) or hdr_objectid,
                "OBJECTCLASS": objectclass,
                "CDHDR_OBJECTID": hdr_objectid,
                "CDPOS_OBJECTID": norm(prow.get("OBJECTID")),
                "TABNAME": norm(prow.get("TABNAME")),
                "FNAME": norm(prow.get("FNAME")),
                "VALUE_OLD": norm(prow.get("VALUE_OLD")),
                "VALUE_NEW": norm(prow.get("VALUE_NEW")),
                "TABKEY": norm(prow.get("TABKEY")) if "TABKEY" in prow.index else "",
            }
            if posnr:
                entry["POSNR"] = norm(posnr)
            key = _change_entry_dedupe_key(entry)
            if key in seen:
                continue
            seen.add(key)
            changes.append(entry)


def research_vbep_changes_for_vbeln(
    vbeln: str,
    cdhdr: pd.DataFrame,
    cdpos: pd.DataFrame,
    *,
    posnr: Optional[str] = None,
    index: Optional[ChangeResearchIndex] = None,
    cmm: Optional[pd.DataFrame] = None,
    cmm_row: Optional[pd.Series] = None,
    mandt: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Run Scenario 2 change-document research for one sales order item.

    Pass a shared ``ChangeResearchIndex`` when processing many VBAP lines.
    When CDHDR.OBJECTID is an internal document id, pass ``cmm`` / ``cmm_row`` so
    we can resolve it from ROOT_DOC / PREDECESSOR_DOC linkage in CMM_VLOGP.
    """
    if index is None:
        index = ChangeResearchIndex.build(cdhdr, cdpos)

    if cdpos.empty or not index.has_required_cdpos_cols:
        return []

    cmm_df = cmm if cmm is not None else pd.DataFrame()
    object_candidates = resolve_cdhdr_object_candidates(
        vbeln,
        posnr or "",
        cmm_df,
        cmm_row,
    )

    changes: List[Dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()

    for obj_key in object_candidates:
        headers = _headers_for_object_key(cdhdr, index, obj_key)
        if headers.empty:
            continue
        _collect_changes_from_headers(
            headers, cdpos, index, posnr, changes, seen
        )

    if mandt and norm(posnr):
        direct = _cdpos_direct_by_tabkey(
            cdpos, mandt, object_candidates, posnr or ""
        )
        direct = _filter_posnr_rows(direct, posnr)
        for _, prow in direct.iterrows():
            oc_col = index.oc_pos_col or "OBJECTCLASS"
            entry = {
                "CHANGENR": norm(prow.get("CHANGENR")),
                "OBJECTID": norm(prow.get("OBJECTID")),
                "OBJECTCLASS": norm(prow.get(oc_col)),
                "CDHDR_OBJECTID": norm(prow.get("OBJECTID")),
                "CDPOS_OBJECTID": norm(prow.get("OBJECTID")),
                "TABNAME": norm(prow.get("TABNAME")),
                "FNAME": norm(prow.get("FNAME")),
                "VALUE_OLD": norm(prow.get("VALUE_OLD")),
                "VALUE_NEW": norm(prow.get("VALUE_NEW")),
                "TABKEY": norm(prow.get("TABKEY")) if "TABKEY" in prow.index else "",
            }
            if posnr:
                entry["POSNR"] = norm(posnr)
            key = _change_entry_dedupe_key(entry)
            if key in seen:
                continue
            seen.add(key)
            changes.append(entry)

    return changes
