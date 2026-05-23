"""Tests for SAP field normalization."""

from app.services.field_compare import (
    canonical_document_key,
    canonical_item_key,
    sap_keys_match,
    values_equal,
)


def test_document_key_trailing_zero_padding():
    assert canonical_document_key("80000010030") == canonical_document_key("800000100300")
    assert canonical_document_key("8000001003") == canonical_document_key("800000100300")


def test_document_key_leading_zeros():
    assert canonical_document_key("008000001003") == canonical_document_key("8000001003")


def test_item_key_leading_zeros_only():
    assert canonical_item_key("000010") == canonical_item_key("10")
    assert canonical_item_key("000010") != canonical_item_key("000100")


def test_sap_keys_match_vbeln_document_char10():
    assert sap_keys_match("80000010030", "800000100300", "000010", "10")
    assert not sap_keys_match("80000010030", "800000100300", "000010", "000020")


def test_values_equal_numeric():
    assert values_equal("100.5", "100.50")
    assert values_equal("1.0", "1")
    assert not values_equal("10", "100")
