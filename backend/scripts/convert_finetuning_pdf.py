#!/usr/bin/env python3
"""One-time conversion: Finetuning PDF section 2 → finetuning_message_mapping.csv"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.services.finetuning_message_map import (  # noqa: E402
    invalidate_finetuning_cache,
    resolve_finetuning_pdf_path,
)
from app.services.finetuning_pdf_extract import (  # noqa: E402
    convert_finetuning_pdf_to_csv,
    extract_finetuning_grid,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Finetuning_Reports_for_Risk_Analysis.pdf to CSV",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=resolve_finetuning_pdf_path() or settings.finetuning_report_pdf,
        help="Path to Finetuning_Reports_for_Risk_Analysis.pdf",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=settings.finetuning_message_map_csv,
        help="Output CSV path",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate CSV even if it is newer than the PDF",
    )
    args = parser.parse_args()

    pdf_path = args.pdf.resolve()
    if not pdf_path.is_file():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    rows = extract_finetuning_grid(pdf_path)
    out_path = convert_finetuning_pdf_to_csv(
        pdf_path,
        args.out.resolve(),
        force=args.force,
    )
    invalidate_finetuning_cache()
    print(f"Wrote {len(rows)} row(s) to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
