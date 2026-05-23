from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from app.config import settings

TABLE_FILES = {
    "VBAP": "vbap.csv",
    "CMM_VLOGP": "cmm_vlogp.csv",
    "QRFC_I_QIN_TOP": "qrfc_i_qin_top.csv",
    "QRFC_I_ERR_STATE": "qrfc_i_err_state.csv",
    "CDHDR": "cdhdr.csv",
    "CDPOS": "cdpos.csv",
}

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


def get_compareable_fields(table: str) -> List[str]:
    """Return CSV columns available for user-selected comparison (excludes join keys)."""
    df = data_store.get(table)
    if df.empty:
        return []
    exclude = VBAP_JOIN_KEYS if table == "VBAP" else CMM_JOIN_KEYS
    return sorted(col for col in df.columns if col not in exclude)


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


def resolve_csv_path(filename: str) -> Tuple[Path, str]:
    """Return active path and source ('upload' | 'sample') for a table CSV."""
    upload_path = settings.upload_dir / filename
    if upload_path.exists():
        return upload_path, "upload"
    return settings.data_dir / filename, "sample"


def resolve_upload_filename(original_name: str) -> Optional[str]:
    """Map SAP export names (e.g. VBAP_May2025.csv) to canonical table CSV filenames."""
    lower = original_name.lower().strip()
    if not lower.endswith(".csv"):
        return None

    allowed = set(TABLE_FILES.values())
    if lower in allowed:
        return lower

    stem = lower[:-4]
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


def stats_for_file(table: str, filename: str) -> dict:
    path, source = resolve_csv_path(filename)
    loaded = path.exists()
    row_count = 0
    column_count = 0
    columns: List[str] = []
    file_size_bytes: Optional[int] = None

    if loaded:
        file_size_bytes = path.stat().st_size
        df = pd.read_csv(path, dtype=str).fillna("")
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
    }


def all_file_stats() -> List[dict]:
    return [stats_for_file(table, filename) for table, filename in TABLE_FILES.items()]


def clear_upload_workspace() -> List[str]:
    """Remove all uploaded CSVs from the server and reload empty in-memory tables."""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    deleted: List[str] = []
    for path in sorted(settings.upload_dir.glob("*.csv")):
        path.unlink()
        deleted.append(path.name)
    data_store._tables.clear()
    data_store.load_all()
    return deleted


class DataStore:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or settings.data_dir
        self._tables: Dict[str, pd.DataFrame] = {}

    def load_all(self) -> Dict[str, pd.DataFrame]:
        for table, filename in TABLE_FILES.items():
            path, _ = resolve_csv_path(filename)
            if path.exists():
                self._tables[table] = pd.read_csv(path, dtype=str).fillna("")
            else:
                self._tables[table] = pd.DataFrame()
        return self._tables

    def get(self, table: str) -> pd.DataFrame:
        if table not in self._tables:
            self.load_all()
        return self._tables.get(table, pd.DataFrame())

    def loaded_tables(self) -> List[str]:
        return [t for t, df in self._tables.items() if not df.empty]

    def reload(self, data_dir: Optional[Path] = None) -> None:
        if data_dir:
            self.data_dir = data_dir
        self._tables.clear()
        self.load_all()


data_store = DataStore()
