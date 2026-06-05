"""Tests for finetuning PDF → CSV extraction."""

from pathlib import Path

from app.config import BACKEND_ROOT, settings
from app.services.finetuning_message_map import (
    invalidate_finetuning_cache,
    load_finetuning_index,
    lookup_finetuning_message,
    resolve_finetuning_pdf_path,
)
from app.services.finetuning_pdf_extract import extract_finetuning_grid


def test_finetuning_pdf_exists_in_project():
    assert resolve_finetuning_pdf_path() is not None


def test_extract_finetuning_grid_from_pdf():
    pdf_path = resolve_finetuning_pdf_path()
    assert pdf_path is not None
    rows = extract_finetuning_grid(pdf_path)
    assert len(rows) >= 22
    ids = {(r["MESSAGE_ID"], r["MESSAGE_NUMBER"]) for r in rows}
    assert ("OPS_SE_PUR_COMMON", "108") in ids
    assert ("SRT_CORE", "143") in ids
    assert ("VF", "750") in ids


def test_lookup_after_pdf_conversion():
    invalidate_finetuning_cache()
    index = load_finetuning_index()
    assert index
    hit = lookup_finetuning_message("CMM_VLOGP", "201")
    assert hit is not None
    assert "inserting" in hit.standard_system_text.lower()
