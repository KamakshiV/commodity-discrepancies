"""Tests for CMM_VLOGP two-step join and finetuning message lookup."""

import pandas as pd

from app.services.finetuning_message_map import (
    invalidate_finetuning_cache,
    load_finetuning_index,
    lookup_finetuning_message,
)
from app.services.rule_engine import (
    RuleEngine,
    _build_cmm_index,
    _build_cmm_predecessor_index,
    _find_cmm_row,
    _is_initial_cmm_version,
)


class _FakeStore:
    def __init__(self, tables):
        self._tables = tables

    def get(self, table: str) -> pd.DataFrame:
        return self._tables.get(table, pd.DataFrame())


def test_is_initial_cmm_version():
    assert _is_initial_cmm_version("0000000000")
    assert _is_initial_cmm_version("0")
    assert not _is_initial_cmm_version("0000000001")


def test_predecessor_join_finds_version_zero_row():
    cmm = pd.DataFrame(
        [
            {
                "DOCUMENT_CHAR10": "9999999999",
                "DOCUMENT_ITEM": "10",
                "PREDECESSOR_DOC": "52004127",
                "PREDECESSOR_DOC_ITM": "10",
                "VERSION": "0000000001",
                "LGORT": "FINV",
            },
            {
                "DOCUMENT_CHAR10": "8888888888",
                "DOCUMENT_ITEM": "10",
                "PREDECESSOR_DOC": "0052004127",
                "PREDECESSOR_DOC_ITM": "000010",
                "VERSION": "0000000000",
                "LGORT": "INTR",
            },
        ]
    )
    pred_index = _build_cmm_predecessor_index(cmm)
    row, path = _find_cmm_row("0052004127", "000010", {}, pred_index)
    assert path == "predecessor"
    assert row is not None
    assert row["LGORT"] == "INTR"


def test_direct_join_preferred_over_predecessor():
    cmm = pd.DataFrame(
        [
            {
                "DOCUMENT_CHAR10": "0052004127",
                "DOCUMENT_ITEM": "000010",
                "PREDECESSOR_DOC": "0052004127",
                "PREDECESSOR_DOC_ITM": "000010",
                "VERSION": "0000000000",
                "LGORT": "DIRECT",
            },
        ]
    )
    direct = _build_cmm_index(cmm)
    pred = _build_cmm_predecessor_index(cmm)
    row, path = _find_cmm_row("0052004127", "000010", direct, pred)
    assert path == "direct"
    assert row["LGORT"] == "DIRECT"


def test_missing_when_no_direct_or_predecessor_match():
    vbap = pd.DataFrame(
        [
            {
                "VBELN": "0052004093",
                "POSNR": "000010",
                "TRMRISK_RELEVANT": "C",
                "MATNR": "A",
            }
        ]
    )
    cmm = pd.DataFrame(
        columns=[
            "DOCUMENT_CHAR10",
            "DOCUMENT_ITEM",
            "PREDECESSOR_DOC",
            "PREDECESSOR_DOC_ITM",
            "VERSION",
            "MATNR",
        ]
    )
    store = _FakeStore(
        {
            "VBAP": vbap,
            "CMM_VLOGP": cmm,
            "QRFC_I_QIN_TOP": pd.DataFrame(),
            "QRFC_I_ERR_STATE": pd.DataFrame(),
            "CDHDR": pd.DataFrame(),
            "CDPOS": pd.DataFrame(),
        }
    )
    engine = RuleEngine(store, scope_vbelns=["0052004093"])
    results = engine.run()
    assert len(results) == 1
    assert results[0].category.value == "Missing in CMM_VLOGP"


def test_direct_join_matches_any_version():
    """Direct join ignores VERSION; highest version wins when duplicates exist."""
    cmm = pd.DataFrame(
        [
            {
                "DOCUMENT_CHAR10": "0052004069",
                "DOCUMENT_ITEM": "000010",
                "VERSION": "0000000001",
                "MATNR": "OLD",
            },
            {
                "DOCUMENT_CHAR10": "0052004069",
                "DOCUMENT_ITEM": "000010",
                "VERSION": "0000000000",
                "MATNR": "NEW",
            },
        ]
    )
    direct = _build_cmm_index(cmm)
    row, path = _find_cmm_row("0052004069", "000010", direct, {})
    assert path == "direct"
    assert row is not None
    assert row["MATNR"] == "OLD"


def test_order_0052004069_posnr_000011_is_category_1():
    """Item 000011 has no CMM_VLOGP row; item 000010 direct-matches on DOCUMENT_CHAR10."""
    from pathlib import Path

    from app.services.data_loader import read_tabular_file

    base = Path(__file__).resolve().parents[1] / "data" / "sample"
    vbap = read_tabular_file(base / "VBAP_May2026.xlsx")
    row = vbap[vbap["VBELN"].astype(str).str.contains("52004069")].iloc[0]
    assert row["POSNR"] == "000010"

    row11 = row.copy()
    row11["POSNR"] = "000011"
    vbap = pd.concat([vbap, pd.DataFrame([row11])], ignore_index=True)

    store = _FakeStore(
        {
            "VBAP": vbap,
            "CMM_VLOGP": read_tabular_file(base / "CMM_VLOGP_May2026_232SalesDocs.xlsx"),
            "QRFC_I_QIN_TOP": read_tabular_file(base / "QRFC_I_QIN_TOP_5000Doc_VBAP.csv"),
            "QRFC_I_ERR_STATE": read_tabular_file(base / "QRFC_I_ERR_STATE_5000Doc_VBAP.csv"),
            "CDHDR": pd.DataFrame(),
            "CDPOS": pd.DataFrame(),
        }
    )
    results = RuleEngine(store, scope_vbelns=["0052004069"]).run()
    by_key = {(r.vbeln, r.posnr): r for r in results}
    assert by_key[("0052004069", "000010")].category.value == "Attribute Mismatch"
    assert by_key[("0052004069", "000011")].category.value == "Missing in CMM_VLOGP"


def test_finetuning_lookup_from_sample_csv():
    invalidate_finetuning_cache()
    index = load_finetuning_index()
    assert index
    hit = lookup_finetuning_message("CMM_VLOGP", "201")
    assert hit is not None
    assert "inserting" in hit.standard_system_text.lower()


def test_finetuning_message_id_fallback_for_live_qrfc_numbers():
    """Live qRFC uses CMM_VLOGP/045 etc.; CSV only has CMM_VLOGP/201."""
    invalidate_finetuning_cache()
    from app.services.finetuning_message_map import (
        extract_qrfc_err_state_fields,
        lookup_finetuning_by_message_id,
        resolve_finetuning_from_qrfc_err,
        resolve_qrfc_finetuning_fields,
    )

    assert lookup_finetuning_message("CMM_VLOGP", "045") is None
    fallback = lookup_finetuning_by_message_id("CMM_VLOGP")
    assert fallback is not None
    assert fallback.sap_component_area == "TRM-CM (Commodity)"
    assert "SMQ2" in fallback.diagnostic_tcode

    resolved = resolve_qrfc_finetuning_fields(
        "CMM_VLOGP",
        "045",
        "Price determination: MtM condition ZMP1 is not active",
    )
    assert resolved["match_type"] == "message_id_fallback"
    assert resolved["sap_component_area"] == "TRM-CM (Commodity)"
    assert "Price determination" in resolved["standard_system_text"]

    message_id, message_number, message = extract_qrfc_err_state_fields(
        {
            "MESSAGE": "Price determination: MtM condition ZMP1 is not active",
            "MESSAGE_ID": "CMM_VLOGP",
            "MESSAGE_NUMBER": "045",
        }
    )
    assert message_id == "CMM_VLOGP"
    assert message_number == "045"
    assert "Price determination" in message

    from_err = resolve_finetuning_from_qrfc_err(
        {
            "MESSAGE": message,
            "MESSAGE_ID": message_id,
            "MESSAGE_NUMBER": message_number,
        }
    )
    assert from_err["match_type"] == "message_id_fallback"
    assert from_err["message_id"] == "CMM_VLOGP"
    assert from_err["message_number"] == "045"
