export interface ExpectedUploadFile {
  id: string;
  filename: string;
  table: string;
  label: string;
  description: string;
}

/** Six SAP tables in upload order. */
export const EXPECTED_UPLOAD_FILES: ExpectedUploadFile[] = [
  {
    id: "vbap",
    filename: "vbap.csv",
    table: "VBAP",
    label: "VBAP",
    description: "Sales document item data (commodity-relevant rows)",
  },
  {
    id: "cmm_vlogp",
    filename: "cmm_vlogp.csv",
    table: "CMM_VLOGP",
    label: "CMM_VLOGP",
    description: "Commodity logistics document items",
  },
  {
    id: "qrfc_i_err_state",
    filename: "qrfc_i_err_state.csv",
    table: "QRFC_I_ERR_STATE",
    label: "qRFC error state",
    description: "Queued RFC error records for root-cause research",
  },
  {
    id: "qrfc_i_qin_top",
    filename: "qrfc_i_qin_top.csv",
    table: "QRFC_I_QIN_TOP",
    label: "qRFC queue",
    description: "Inbound qRFC queue header records",
  },
  {
    id: "cdhdr",
    filename: "cdhdr.csv",
    table: "CDHDR",
    label: "CDHDR",
    description: "Change document headers",
  },
  {
    id: "cdpos",
    filename: "cdpos.csv",
    table: "CDPOS",
    label: "CDPOS",
    description: "Change document item positions",
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
  if (!lower.endsWith(".csv")) return null;

  if (CANONICAL_FILENAMES.has(lower)) return lower;

  const stem = lower.slice(0, -4);
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

export function expectedFilenameHint(): string {
  return EXPECTED_UPLOAD_FILES.map((f) => f.filename).join(", ");
}
