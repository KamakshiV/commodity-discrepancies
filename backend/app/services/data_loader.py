import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from app.config import settings
from app.services.field_compare import canonical_document_key, norm

TABLE_FILES = {
    "VBAP": "vbap.csv",
    "CMM_VLOGP": "cmm_vlogp.csv",
    "QRFC_I_QIN_TOP": "qrfc_i_qin_top.csv",
    "QRFC_I_ERR_STATE": "qrfc_i_err_state.csv",
    "CDHDR": "cdhdr.csv",
    "CDPOS": "cdpos.csv",
}

SUPPORTED_DATA_EXTENSIONS = (".csv", ".xlsx", ".xls", ".xlsm")

TABLE_ORDER = list(TABLE_FILES.keys())

# Default attribute mappings (placeholder until Arvid provides final list)
DEFAULT_COMPARE_MAPPINGS = [
    {"vbap_field": "MATNR", "cmm_field": "MATERIAL", "enabled": True},
    {"vbap_field": "KWMENG", "cmm_field": "QUANTITY", "enabled": True},
    {"vbap_field": "VRKME", "cmm_field": "UNIT", "enabled": True},
]

VBAP_JOIN_KEYS = {"VBELN", "POSNR", "TRMRISK_RELEVANT"}
CMM_JOIN_KEYS = {"DOCUMENT_CHAR10", "DOCUMENT_ITEM"}
COMMODITY_FILTER_COLUMN = "TRMRISK_RELEVANT"


def filter_commodity_relevant(vbap: pd.DataFrame) -> pd.DataFrame:
    """
    Return VBAP rows to reconcile.

    When TRMRISK_RELEVANT exists, keep only rows with value 'C' (commodity-relevant).
    When the column is absent (full SAP extract), process all loaded VBAP rows.
    """
    if vbap.empty:
        return vbap
    if COMMODITY_FILTER_COLUMN in vbap.columns:
        return vbap[vbap[COMMODITY_FILTER_COLUMN].astype(str).str.strip() == "C"].copy()
    return vbap.copy()


def count_commodity_relevant(vbap: pd.DataFrame) -> int:
    return len(filter_commodity_relevant(vbap))


def normalize_erdat(val) -> str:
    """Normalize SAP ERDAT to YYYYMMDD for comparison.

    Handles common SAP export formats:
    - YYYYMMDD / YYYY-MM-DD (ISO)
    - DD.MM.YYYY (SAP GUI export)
    - MM/DD/YYYY (US)
    """
    s = norm(val)
    if not s:
        return ""

    # DD.MM.YYYY — typical SAP GUI / European export
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", s)
    if m:
        day, month, year = m.groups()
        return f"{year}{int(month):02d}{int(day):02d}"

    # YYYY-MM-DD or YYYY/MM/DD
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        year, month, day = m.groups()
        return f"{year}{int(month):02d}{int(day):02d}"

    # MM/DD/YYYY — US date picker display
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        month, day, year = m.groups()
        return f"{year}{int(month):02d}{int(day):02d}"

    digits = re.sub(r"[^0-9]", "", s)
    if len(digits) == 8:
        # Already YYYYMMDD when year prefix is 19xx/20xx
        if digits[:2] in ("19", "20"):
            return digits
        # DDMMYYYY compact (e.g. 17062025)
        day, month, year = int(digits[0:2]), int(digits[2:4]), digits[4:8]
        if day <= 31 and month <= 12:
            return f"{year}{month:02d}{day:02d}"
        return digits

    return digits[:8] if len(digits) >= 8 else digits


def filter_vbap_scope(
    vbap: pd.DataFrame,
    *,
    vbelns: Optional[List[str]] = None,
    erdat: Optional[str] = None,
) -> pd.DataFrame:
    """Apply commodity filter plus optional VBELN list or ERDAT scope."""
    df = filter_commodity_relevant(vbap)
    if df.empty:
        return df

    if vbelns:
        targets = {canonical_document_key(v) for v in vbelns if norm(v)}
        if targets:
            df = df[
                df["VBELN"].apply(lambda x: canonical_document_key(x) in targets)
            ].copy()

    if erdat:
        target_date = normalize_erdat(erdat)
        if target_date and "ERDAT" in df.columns:
            df = df[
                df["ERDAT"].apply(lambda x: normalize_erdat(x) == target_date)
            ].copy()

    return df


def preview_scope(
    vbap: pd.DataFrame,
    *,
    mode: str = "vbeln",
    vbelns: Optional[List[str]] = None,
    erdat: Optional[str] = None,
) -> dict:
    """Return row/order counts for UI scope preview."""
    commodity = filter_commodity_relevant(vbap)
    total = len(commodity)
    vbap_loaded = not vbap.empty
    has_erdat = "ERDAT" in vbap.columns

    if mode == "vbeln":
        requested = [norm(v) for v in (vbelns or []) if norm(v)]
        if not requested:
            return {
                "mode": mode,
                "vbap_loaded": vbap_loaded,
                "has_erdat_column": has_erdat,
                "commodity_relevant_total": total,
                "matching_rows": 0,
                "matching_orders": 0,
                "matched_vbelns": [],
                "unknown_vbelns": [],
                "sample_vbelns": _sample_vbelns(commodity),
                "message": "Enter at least one sales order (VBELN).",
            }
        scoped = filter_vbap_scope(vbap, vbelns=requested)
        matched_keys = {
            canonical_document_key(v)
            for v in scoped["VBELN"].tolist()
            if norm(v)
        }
        matched_vbelns = sorted({norm(v) for v in scoped["VBELN"].tolist() if norm(v)})
        unknown = [
            v
            for v in requested
            if canonical_document_key(v) not in matched_keys
        ]
        return {
            "mode": mode,
            "vbap_loaded": vbap_loaded,
            "has_erdat_column": has_erdat,
            "commodity_relevant_total": total,
            "matching_rows": len(scoped),
            "matching_orders": scoped["VBELN"].nunique() if not scoped.empty else 0,
            "matched_vbelns": matched_vbelns,
            "unknown_vbelns": unknown,
            "sample_vbelns": _sample_vbelns(commodity),
            "message": (
                f"{len(scoped)} line(s) across {scoped['VBELN'].nunique() if not scoped.empty else 0} order(s)"
                if not scoped.empty
                else "No matching VBAP rows for the entered VBELN value(s)."
            ),
        }

    if mode == "erdat":
        target = normalize_erdat(erdat or "")
        if not target:
            return {
                "mode": mode,
                "vbap_loaded": vbap_loaded,
                "has_erdat_column": has_erdat,
                "commodity_relevant_total": total,
                "matching_rows": 0,
                "matching_orders": 0,
                "matched_vbelns": [],
                "unknown_vbelns": [],
                "sample_vbelns": _sample_vbelns(commodity),
                "message": "Select a creation date (ERDAT).",
            }
        if not has_erdat:
            return {
                "mode": mode,
                "vbap_loaded": vbap_loaded,
                "has_erdat_column": False,
                "commodity_relevant_total": total,
                "matching_rows": 0,
                "matching_orders": 0,
                "matched_vbelns": [],
                "unknown_vbelns": [],
                "sample_vbelns": _sample_vbelns(commodity),
                "message": "VBAP has no ERDAT column in the shared drive export.",
            }
        scoped = filter_vbap_scope(vbap, erdat=target)
        return {
            "mode": mode,
            "vbap_loaded": vbap_loaded,
            "has_erdat_column": has_erdat,
            "commodity_relevant_total": total,
            "matching_rows": len(scoped),
            "matching_orders": scoped["VBELN"].nunique() if not scoped.empty else 0,
            "matched_vbelns": sorted({norm(v) for v in scoped["VBELN"].tolist() if norm(v)}),
            "unknown_vbelns": [],
            "sample_vbelns": _sample_vbelns(commodity),
            "message": (
                f"{len(scoped)} line(s) on ERDAT {target}"
                if not scoped.empty
                else f"No commodity-relevant VBAP rows for ERDAT {target}."
            ),
        }

    return {
        "mode": mode,
        "vbap_loaded": vbap_loaded,
        "has_erdat_column": has_erdat,
        "commodity_relevant_total": total,
        "matching_rows": 0,
        "matching_orders": 0,
        "matched_vbelns": [],
        "unknown_vbelns": [],
        "sample_vbelns": _sample_vbelns(commodity),
        "message": f"Unknown scope mode: {mode}. Use vbeln or erdat.",
    }


def _sample_vbelns(vbap: pd.DataFrame, limit: int = 5) -> List[str]:
    if vbap.empty or "VBELN" not in vbap.columns:
        return []
    seen: set[str] = set()
    samples: List[str] = []
    for val in vbap["VBELN"].tolist():
        s = norm(val)
        if not s or s in seen:
            continue
        seen.add(s)
        samples.append(s)
        if len(samples) >= limit:
            break
    return samples


def build_scope_label(
    mode: str,
    vbelns: Optional[List[str]] = None,
    erdat: Optional[str] = None,
) -> str:
    if mode == "vbeln" and vbelns:
        shown = ", ".join(norm(v) for v in vbelns if norm(v))
        return f"Scoped to VBAP.VBELN: {shown}"
    if mode == "erdat" and erdat:
        return f"Scoped to VBAP.ERDAT: {normalize_erdat(erdat)}"
    return "VBAP scope not specified"


def get_compareable_fields(table: str) -> List[str]:
    """Return CSV columns available for user-selected comparison (excludes join keys)."""
    df = data_store.get(table)
    if len(df.columns) == 0:
        return []
    exclude = VBAP_JOIN_KEYS if table == "VBAP" else CMM_JOIN_KEYS
    return sorted(col for col in df.columns if col not in exclude)


def build_default_compare_mappings() -> List[dict]:
    """
    Build default VBAP ↔ CMM_VLOGP mappings for the UI.

    1. Pair fields that share the same column name in both tables (e.g. MATNR → MATNR).
    2. Append preset mappings (MATNR → MATERIAL, etc.) when not already covered.
    """
    vbap_fields = set(get_compareable_fields("VBAP"))
    cmm_fields = set(get_compareable_fields("CMM_VLOGP"))
    common_names = sorted(vbap_fields & cmm_fields)

    mappings: List[dict] = []
    seen_vbap: set[str] = set()

    for name in common_names:
        mappings.append({"vbap_field": name, "cmm_field": name, "enabled": True})
        seen_vbap.add(name)

    for preset in DEFAULT_COMPARE_MAPPINGS:
        vbap_f = preset["vbap_field"]
        cmm_f = preset["cmm_field"]
        if vbap_f in seen_vbap:
            continue
        if vbap_fields and vbap_f not in vbap_fields:
            continue
        if cmm_fields and cmm_f not in cmm_fields:
            continue
        mappings.append(
            {
                "vbap_field": vbap_f,
                "cmm_field": cmm_f,
                "enabled": preset.get("enabled", True),
            }
        )
        seen_vbap.add(vbap_f)

    if not mappings:
        return [dict(m) for m in DEFAULT_COMPARE_MAPPINGS]

    return mappings


def mappings_to_tuples(mappings: List[dict]) -> List[tuple]:
    """Convert API mappings to (vbap_field, cmm_field) pairs for the rule engine."""
    pairs: List[tuple] = []
    for m in mappings:
        if not m.get("enabled", True):
            continue
        vbap_f = str(m.get("vbap_field", "")).strip()
        cmm_f = str(m.get("cmm_field", "")).strip()
        if vbap_f and cmm_f:
            pairs.append((vbap_f, cmm_f))
    return pairs


def resolve_upload_filename(original_name: str) -> Optional[str]:
    """Map SAP export names (e.g. VBAP_May2025.csv) to canonical table filenames."""
    stem = _data_file_stem(original_name)
    if stem is None:
        return None

    allowed = set(TABLE_FILES.values())
    for ext in SUPPORTED_DATA_EXTENSIONS:
        candidate = f"{stem}{ext}"
        if candidate in allowed:
            return candidate

    patterns = [
        ("qrfc_i_err_state.csv", ["qrfc_i_err_state"]),
        ("qrfc_i_qin_top.csv", ["qrfc_i_qin_top"]),
        ("cmm_vlogp.csv", ["cmm_vlogp"]),
        ("vbap.csv", ["vbap"]),
        ("cdhdr.csv", ["cdhdr"]),
        ("cdpos.csv", ["cdpos"]),
    ]
    for filename, stems in patterns:
        for pattern in stems:
            if stem == pattern or stem.startswith(f"{pattern}_") or stem.startswith(f"{pattern}-"):
                return filename
    return None


def _data_file_stem(name: str) -> Optional[str]:
    """Return lowercase stem for a supported CSV/Excel filename."""
    lower = name.lower().strip()
    for ext in SUPPORTED_DATA_EXTENSIONS:
        if lower.endswith(ext):
            return lower[: -len(ext)]
    return None


def _canonical_stem(canonical_filename: str) -> str:
    stem = _data_file_stem(canonical_filename)
    return stem if stem else canonical_filename.lower().removesuffix(".csv")


def read_tabular_file(path: Path) -> pd.DataFrame:
    """Load a SAP export from CSV or Excel (.xlsx / .xls / .xlsm)."""
    ext = path.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path, dtype=str).fillna("")
    if ext in (".xlsx", ".xlsm"):
        return pd.read_excel(path, dtype=str, engine="openpyxl").fillna("")
    if ext == ".xls":
        return pd.read_excel(path, dtype=str, engine="xlrd").fillna("")
    raise ValueError(f"Unsupported data file format: {path.suffix}")


def sync_data_source() -> dict:
    """Sync from Google Drive when configured; rescan local folder otherwise."""
    invalidate_local_csv_index()
    if not settings.uses_google_drive:
        index = build_local_csv_index()
        found = sorted(index.keys())
        missing = sorted(set(TABLE_FILES.values()) - set(found))
        message = f"Found {len(found)} data file(s) in {settings.shared_data_dir}."
        if missing:
            message += f" Missing: {', '.join(missing)}."
        data_store._require_reload = False
        return {
            "synced": True,
            "skipped": False,
            "downloaded": found,
            "message": message,
        }
    from app.services.google_drive_sync import sync_from_google_drive

    result = sync_from_google_drive()
    invalidate_local_csv_index()
    data_store._require_reload = False
    return {
        "synced": result.synced,
        "skipped": result.skipped,
        "downloaded": result.downloaded,
        "drive_files_seen": result.drive_files_seen,
        "message": result.message,
    }


def _file_source_label() -> str:
    if settings.uses_google_drive:
        return "google_drive"
    return "local"


_local_data_index_cache: Optional[Dict[str, Path]] = None


def invalidate_local_csv_index() -> None:
    global _local_data_index_cache
    _local_data_index_cache = None


def build_local_csv_index() -> Dict[str, Path]:
    """Map canonical table filenames to paths on disk (CSV or Excel)."""
    global _local_data_index_cache
    if _local_data_index_cache is not None:
        return _local_data_index_cache

    index: Dict[str, Path] = {}
    data_dir = settings.shared_data_dir
    if data_dir.is_dir():
        data_files: List[Path] = []
        for ext in SUPPORTED_DATA_EXTENSIONS:
            data_files.extend(data_dir.glob(f"*{ext}"))
        data_files = sorted(
            data_files,
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in data_files:
            canonical = resolve_upload_filename(path.name)
            if canonical and canonical not in index:
                index[canonical] = path

    _local_data_index_cache = index
    return index


def resolve_csv_path(filename: str) -> Tuple[Path, str]:
    """Return path and source for a table file (CSV or Excel) in the data folder."""
    data_dir = settings.shared_data_dir
    canonical_path = data_dir / filename
    if canonical_path.exists():
        return canonical_path, _file_source_label()

    stem = _canonical_stem(filename)
    for ext in SUPPORTED_DATA_EXTENSIONS:
        alt = data_dir / f"{stem}{ext}"
        if alt.exists():
            return alt, _file_source_label()

    matched = build_local_csv_index().get(filename)
    if matched and matched.exists():
        return matched, _file_source_label()

    return canonical_path, "missing"


def stats_for_file(table: str, filename: str) -> dict:
    path, source = resolve_csv_path(filename)
    loaded = path.exists()
    row_count = 0
    column_count = 0
    columns: List[str] = []
    file_size_bytes: Optional[int] = None

    if loaded:
        file_size_bytes = path.stat().st_size
        df = read_tabular_file(path)
        row_count = len(df)
        columns = list(df.columns)
        column_count = len(columns)

    return {
        "filename": filename,
        "table": table,
        "loaded": loaded,
        "row_count": row_count,
        "column_count": column_count,
        "columns": columns,
        "file_size_bytes": file_size_bytes,
        "source": source if loaded else "missing",
        "resolved_filename": path.name if loaded else None,
    }


def all_file_stats() -> List[dict]:
    return [stats_for_file(table, filename) for table, filename in TABLE_FILES.items()]


def clear_data_cache() -> dict:
    """
    Clear in-memory tables and require an explicit reload before analysis.

    For Google Drive, also deletes downloaded CSV/Excel copies from the cache folder.
    Local source exports (e.g. VBAP_May2025.csv) on disk are not deleted.
    """
    invalidate_local_csv_index()
    deleted: List[str] = []
    cache_dir = settings.shared_data_dir

    if settings.uses_google_drive and cache_dir.is_dir():
        for ext in SUPPORTED_DATA_EXTENSIONS:
            for path in sorted(cache_dir.glob(f"*{ext}")):
                path.unlink(missing_ok=True)
                deleted.append(path.name)

    data_store._tables.clear()
    for table in TABLE_FILES:
        data_store._tables[table] = pd.DataFrame()
    data_store._require_reload = True

    if deleted:
        message = f"Cleared session and removed {len(deleted)} cached file(s)."
    else:
        message = "Session and in-memory cache cleared. Reload data to continue."

    return {
        "cleared": True,
        "deleted_files": deleted,
        "message": message,
    }


class DataStore:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or settings.shared_data_dir
        self._tables: Dict[str, pd.DataFrame] = {}
        self._require_reload: bool = False

    def load_all(self) -> Dict[str, pd.DataFrame]:
        if self._require_reload:
            return self._tables
        settings.shared_data_dir.mkdir(parents=True, exist_ok=True)
        invalidate_local_csv_index()
        for table, filename in TABLE_FILES.items():
            path, _ = resolve_csv_path(filename)
            if path.exists():
                self._tables[table] = read_tabular_file(path)
            else:
                self._tables[table] = pd.DataFrame()
        return self._tables

    def get(self, table: str) -> pd.DataFrame:
        if self._require_reload:
            return self._tables.get(table, pd.DataFrame())
        if table not in self._tables:
            self.load_all()
        return self._tables.get(table, pd.DataFrame())

    def loaded_tables(self) -> List[str]:
        return [t for t, df in self._tables.items() if not df.empty]

    def reload(self, data_dir: Optional[Path] = None) -> None:
        if data_dir:
            self.data_dir = data_dir
        self._require_reload = False
        self._tables.clear()
        self.load_all()


data_store = DataStore()
