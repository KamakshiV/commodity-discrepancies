"""Tests for dynamic default attribute mapping suggestions."""

import pandas as pd

from app.services import data_loader
from app.services.data_loader import (
    DEFAULT_COMPARE_MAPPINGS,
    build_default_compare_mappings,
    data_store,
)


def test_same_name_fields_suggested_first():
    data_store._tables["VBAP"] = pd.DataFrame(
        columns=["VBELN", "POSNR", "MATNR", "KWMENG", "VRKME", "CUSTOM1"]
    )
    data_store._tables["CMM_VLOGP"] = pd.DataFrame(
        columns=["DOCUMENT_CHAR10", "DOCUMENT_ITEM", "MATNR", "QUANTITY", "CUSTOM1"]
    )

    mappings = build_default_compare_mappings()
    pairs = [(m["vbap_field"], m["cmm_field"]) for m in mappings]

    assert ("MATNR", "MATNR") in pairs
    assert ("CUSTOM1", "CUSTOM1") in pairs
    assert pairs.index(("MATNR", "MATNR")) < pairs.index(("KWMENG", "QUANTITY"))


def test_preset_mappings_appended_when_columns_exist():
    data_store._tables["VBAP"] = pd.DataFrame(
        columns=["VBELN", "POSNR", "MATNR", "KWMENG", "VRKME"]
    )
    data_store._tables["CMM_VLOGP"] = pd.DataFrame(
        columns=["DOCUMENT_CHAR10", "DOCUMENT_ITEM", "MATERIAL", "QUANTITY", "UNIT"]
    )

    mappings = build_default_compare_mappings()
    pairs = [(m["vbap_field"], m["cmm_field"]) for m in mappings]

    assert ("MATNR", "MATNR") not in pairs
    assert ("MATNR", "MATERIAL") in pairs
    assert ("KWMENG", "QUANTITY") in pairs


def test_falls_back_to_static_presets_when_no_data():
    data_store._tables["VBAP"] = pd.DataFrame()
    data_store._tables["CMM_VLOGP"] = pd.DataFrame()

    mappings = build_default_compare_mappings()
    assert len(mappings) == len(DEFAULT_COMPARE_MAPPINGS)
