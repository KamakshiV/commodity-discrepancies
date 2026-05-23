"""SAP field normalization for cross-table key and attribute comparison."""

from typing import Any


def norm(val: Any) -> str:
    return str(val).strip() if val is not None else ""


def _is_numeric_string(s: str) -> bool:
    if not s:
        return False
    cleaned = s.replace(".", "", 1).replace("-", "", 1)
    return cleaned.isdigit()


def canonical_document_key(val: Any) -> str:
    """
    Normalize VBELN / DOCUMENT_CHAR10.

    SAP char fields may pad the same sales document with different trailing zeros
    (e.g. VBAP ``80000010030`` vs CMM ``800000100300``). Strip leading and
    trailing zeros on numeric values so the core document id compares equal.
    """
    s = norm(val)
    if not s:
        return ""
    if _is_numeric_string(s):
        core = s.lstrip("0") or "0"
        core = core.rstrip("0") or "0"
        return core
    return s.upper()


def canonical_item_key(val: Any) -> str:
    """
    Normalize POSNR / DOCUMENT_ITEM.

    Item numbers use leading-zero padding, not trailing-zero padding — only
    strip leading zeros (``000010`` and ``10`` compare equal).
    """
    s = norm(val)
    if not s:
        return ""
    if _is_numeric_string(s):
        return s.lstrip("0") or "0"
    return s.upper()


def sap_keys_match(
    vbeln: Any,
    document_char10: Any,
    posnr: Any,
    document_item: Any,
) -> bool:
    return canonical_document_key(vbeln) == canonical_document_key(document_char10) and (
        canonical_item_key(posnr) == canonical_item_key(document_item)
    )


def values_equal(vbap_val: Any, cmm_val: Any) -> bool:
    """
    Compare two mapped attribute values field-to-field.

    Uses exact match first, then numeric equivalence for quantities/amounts where
    formatting differs (trailing zeros, ``1.0`` vs ``1``).
    """
    a = norm(vbap_val)
    b = norm(cmm_val)
    if a == b:
        return True
    if a == "" and b == "":
        return True

    if _is_numeric_string(a) and _is_numeric_string(b):
        try:
            return float(a) == float(b)
        except ValueError:
            pass

    return False
