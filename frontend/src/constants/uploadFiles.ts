export interface ExpectedUploadFile {
  id: string;
  filename: string;
  table: string;
  label: string;
  description: string;
}

const DATA_FILE_EXTENSIONS = [".csv", ".xlsx", ".xls", ".xlsm"] as const;

/** Six SAP tables in upload order. */
export const EXPECTED_UPLOAD_FILES: ExpectedUploadFile[] = [
  {
    id: "vbap",
    filename: "vbap.csv",
    table: "VBAP",
    label: "VBAP",
    description: "Sales document item data (CSV or Excel)",
  },
  {
    id: "cmm_vlogp",
    filename: "cmm_vlogp.csv",
    table: "CMM_VLOGP",
    label: "CMM_VLOGP",
    description: "Commodity logistics document items (CSV or Excel)",
  },
  {
    id: "qrfc_i_err_state",
    filename: "qrfc_i_err_state.csv",
    table: "QRFC_I_ERR_STATE",
    label: "qRFC error state",
    description: "Queued RFC error records (CSV or Excel)",
  },
  {
    id: "qrfc_i_qin_top",
    filename: "qrfc_i_qin_top.csv",
    table: "QRFC_I_QIN_TOP",
    label: "qRFC queue",
    description: "Inbound qRFC queue header records (CSV or Excel)",
  },
  {
    id: "cdhdr",
    filename: "cdhdr.csv",
    table: "CDHDR",
    label: "CDHDR",
    description: "Change document headers (CSV or Excel)",
  },
  {
    id: "cdpos",
    filename: "cdpos.csv",
    table: "CDPOS",
    label: "CDPOS",
    description: "Change document item positions (CSV or Excel)",
  },
];

/**
 * Map SAP export filenames (e.g. VBAP_May2025.csv) to canonical upload names.
 * Longest stems first so qrfc_i_err_state is not matched as qrfc_i_qin_top.
 */
const CANONICAL_UPLOAD_PATTERNS: { filename: string; stems: string[] }[] = [
  { filename: "qrfc_i_err_state.csv", stems: ["qrfc_i_err_state"] },
  { filename: "qrfc_i_qin_top.csv", stems: ["qrfc_i_qin_top"] },
  { filename: "cmm_vlogp.csv", stems: ["cmm_vlogp"] },
  { filename: "vbap.csv", stems: ["vbap"] },
  { filename: "cdhdr.csv", stems: ["cdhdr"] },
  { filename: "cdpos.csv", stems: ["cdpos"] },
];

const CANONICAL_FILENAMES = new Set(
  EXPECTED_UPLOAD_FILES.map((f) => f.filename.toLowerCase())
);

export function resolveUploadFilename(originalName: string): string | null {
  const lower = originalName.toLowerCase().trim();
  const ext = DATA_FILE_EXTENSIONS.find((suffix) => lower.endsWith(suffix));
  if (!ext) return null;

  if (CANONICAL_FILENAMES.has(lower)) return lower;

  const stem = lower.slice(0, -ext.length);
  for (const { filename, stems } of CANONICAL_UPLOAD_PATTERNS) {
    for (const pattern of stems) {
      if (
        stem === pattern ||
        stem.startsWith(`${pattern}_`) ||
        stem.startsWith(`${pattern}-`)
      ) {
        return filename;
      }
    }
  }
  return null;
}

export function formatHintForTable(canonicalFilename: string): string {
  const stem = canonicalFilename.replace(/\.csv$/i, "");
  return `${stem}.csv / ${stem}.xlsx / ${stem}.xls`;
}

export function expectedFilenameHint(): string {
  return EXPECTED_UPLOAD_FILES.map((f) => formatHintForTable(f.filename)).join(", ");
}
