import { useEffect, useMemo, useState } from "react";
import type { DataInputMode, FileUploadStats, ScopePreviewResponse } from "../types";
import { EXPECTED_UPLOAD_FILES, formatHintForTable } from "../constants/uploadFiles";
import { fetchScopePreview } from "../services/api";

function formatBytes(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function parseVbelnInput(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(/[\s,;\n]+/)
        .map((s) => s.trim())
        .filter(Boolean)
    ),
  ];
}

function isoToSapErdat(iso: string): string {
  return iso.replace(/-/g, "");
}

function sapErdatToIso(sap: string): string {
  const d = sap.replace(/\D/g, "");
  if (d.length !== 8) return "";
  return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`;
}

const INPUT_METHODS: {
  id: DataInputMode;
  title: string;
  subtitle: string;
  icon: string;
}[] = [
  {
    id: "vbeln",
    title: "Sales order (VBELN)",
    subtitle: "Filter by one or more VBAP.VBELN values",
    icon: "🔢",
  },
  {
    id: "erdat",
    title: "Creation date (ERDAT)",
    subtitle: "Filter by VBAP.ERDAT",
    icon: "📅",
  },
];

interface Props {
  dataSource: string;
  sharedDataDir: string | null;
  googleDriveFolderId: string | null;
  googleDriveConfigured: boolean;
  fileStats: Record<string, FileUploadStats>;
  dataReady: boolean;
  reloading: boolean;
  inputMode: DataInputMode;
  vbelns: string[];
  erdat: string;
  onInputModeChange: (mode: DataInputMode) => void;
  onVbelnsChange: (vbelns: string[]) => void;
  onErdatChange: (erdat: string) => void;
  onReload: () => void;
  onContinue: () => void;
}

function sourceLabel(source: string): string {
  if (source === "google_drive") return "Google Drive";
  if (source === "local") return "Local cache";
  return source;
}

export default function DataInputPanel({
  dataSource,
  sharedDataDir,
  googleDriveFolderId,
  googleDriveConfigured,
  fileStats,
  dataReady,
  reloading,
  inputMode,
  vbelns,
  erdat,
  onInputModeChange,
  onVbelnsChange,
  onErdatChange,
  onReload,
  onContinue,
}: Props) {
  const [vbelnDraft, setVbelnDraft] = useState("");
  const [preview, setPreview] = useState<ScopePreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [showDataFiles, setShowDataFiles] = useState(true);

  const rows = EXPECTED_UPLOAD_FILES.map((expected, idx) => ({
    ...expected,
    index: idx + 1,
    stats: fileStats[expected.filename],
  }));

  const filesOnDiskCount = rows.filter((r) => r.stats?.loaded).length;
  const allOnDisk = filesOnDiskCount === EXPECTED_UPLOAD_FILES.length;
  const memoryLoadedCount = dataReady ? filesOnDiskCount : 0;
  const missingFiles = rows
    .filter((r) => !r.stats?.loaded)
    .map((r) => r.filename);
  const vbapOnDisk = !!fileStats["vbap.csv"]?.loaded;
  const vbapInMemory = dataReady && vbapOnDisk;

  const canContinue = useMemo(() => {
    if (!allOnDisk || !dataReady) return false;
    if (inputMode === "vbeln") {
      return vbelns.length > 0 && (preview?.matching_rows ?? 0) > 0;
    }
    if (inputMode === "erdat") {
      return !!erdat && (preview?.matching_rows ?? 0) > 0;
    }
    return false;
  }, [allOnDisk, dataReady, inputMode, vbelns, erdat, preview]);

  useEffect(() => {
    if (!dataReady) {
      setPreview(null);
      return;
    }
    const timer = window.setTimeout(async () => {
      setPreviewLoading(true);
      try {
        const result = await fetchScopePreview({
          mode: inputMode,
          vbelns,
          erdat,
        });
        setPreview(result);
      } catch {
        setPreview(null);
      } finally {
        setPreviewLoading(false);
      }
    }, 350);
    return () => window.clearTimeout(timer);
  }, [inputMode, vbelns, erdat, filesOnDiskCount, dataReady]);

  const addVbelnFromDraft = () => {
    const next = parseVbelnInput(vbelnDraft);
    if (!next.length) return;
    onVbelnsChange([...new Set([...vbelns, ...next])]);
    setVbelnDraft("");
  };

  const removeVbeln = (value: string) => {
    onVbelnsChange(vbelns.filter((v) => v !== value));
  };

  const usesGoogleDrive = dataSource === "google_drive";
  const reloadLabel = usesGoogleDrive ? "Sync from Google Drive" : "Reload from folder";

  return (
    <section className="step-panel upload-panel">
      <div className="step-panel-top">
        <div className="step-panel-header">
          <span className="step-badge">Step 1</span>
          <h2>Select data source</h2>
          <p>
            {usesGoogleDrive
              ? "SAP CSV exports are synced from Google Drive into a server cache. Choose how to scope the analysis."
              : "SAP CSV exports are read from a folder on the server. Choose how to scope the analysis."}
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary step-panel-top-action"
          onClick={onContinue}
          disabled={!canContinue || reloading}
        >
          Continue to attribute mapping
        </button>
      </div>

      <div className="shared-drive-banner">
        <div className="shared-drive-info">
          <span className="shared-drive-label">
            {usesGoogleDrive ? "Google Drive" : "Local folder"}
          </span>
          {usesGoogleDrive && googleDriveFolderId ? (
            <code className="shared-drive-path">Folder ID: {googleDriveFolderId}</code>
          ) : (
            <code className="shared-drive-path">{sharedDataDir || "Not configured"}</code>
          )}
          <span className="shared-drive-cache muted">
            Cache: {sharedDataDir || "—"}
            {usesGoogleDrive && !googleDriveConfigured && (
              <span className="shared-drive-warn"> · credentials missing</span>
            )}
          </span>
        </div>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          onClick={onReload}
          disabled={reloading}
        >
          {reloading ? "Syncing…" : reloadLabel}
        </button>
      </div>

      {!dataReady && allOnDisk && (
        <div className="upload-missing-alert" role="alert">
          Data is not loaded in memory. Click <strong>{reloadLabel}</strong> before continuing.
        </div>
      )}

      {!allOnDisk && (
        <div className="upload-missing-alert" role="alert">
          <strong>{missingFiles.length} file(s) missing:</strong>{" "}
          {missingFiles.map((name, i) => (
            <span key={name}>
              <code>{name}</code>
              {i < missingFiles.length - 1 ? ", " : ""}
            </span>
          ))}
          .{" "}
          {usesGoogleDrive
            ? "Add CSV or Excel files to the Google Drive folder, then click Sync from Google Drive."
            : "Place all six SAP exports (CSV or Excel) in the folder, then click Reload."}
        </div>
      )}

      <div className="input-method-grid" role="radiogroup" aria-label="Data input method">
        {INPUT_METHODS.map((method) => {
          const selected = inputMode === method.id;
          return (
            <button
              key={method.id}
              type="button"
              role="radio"
              aria-checked={selected}
              className={`input-method-card ${selected ? "selected" : ""}`}
              onClick={() => onInputModeChange(method.id)}
              disabled={!allOnDisk}
            >
              <span className="input-method-icon" aria-hidden>
                {method.icon}
              </span>
              <span className="input-method-title">{method.title}</span>
              <span className="input-method-subtitle">{method.subtitle}</span>
              {selected && <span className="input-method-check" aria-hidden>✓</span>}
            </button>
          );
        })}
      </div>

      <div className={`input-method-panel panel-${inputMode}`}>
        {inputMode === "vbeln" && (
          <div className="vbeln-input-panel">
            <label className="vbeln-input-label" htmlFor="vbeln-entry">
              VBAP.VBELN — sales document number(s)
            </label>
            <p className="vbeln-input-hint">
              Type or paste one or more order numbers from the shared drive VBAP
              export. Press Enter or Add to create chips.
            </p>
            <div className="vbeln-chip-row">
              {vbelns.map((v) => {
                const unknown = preview?.unknown_vbelns.includes(v);
                return (
                  <span
                    key={v}
                    className={`vbeln-chip ${unknown ? "unknown" : "matched"}`}
                  >
                    <span className="vbeln-chip-value">{v}</span>
                    <button
                      type="button"
                      className="vbeln-chip-remove"
                      onClick={() => removeVbeln(v)}
                      aria-label={`Remove ${v}`}
                    >
                      ×
                    </button>
                  </span>
                );
              })}
              {vbelns.length === 0 && (
                <span className="vbeln-chip-placeholder">No VBELN added yet</span>
              )}
            </div>
            <div className="vbeln-entry-row">
              <input
                id="vbeln-entry"
                type="text"
                className="vbeln-text-input"
                placeholder="e.g. 80000010030 or paste comma-separated list"
                value={vbelnDraft}
                onChange={(e) => setVbelnDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addVbelnFromDraft();
                  }
                }}
              />
              <button
                type="button"
                className="btn btn-outline"
                onClick={addVbelnFromDraft}
                disabled={!vbelnDraft.trim()}
              >
                Add
              </button>
            </div>
            {preview?.sample_vbelns.length ? (
              <div className="vbeln-suggestions">
                <span className="vbeln-suggestions-label">From shared drive:</span>
                {preview.sample_vbelns.map((sample) => (
                  <button
                    key={sample}
                    type="button"
                    className="vbeln-suggestion-chip"
                    onClick={() => {
                      if (!vbelns.includes(sample)) {
                        onVbelnsChange([...vbelns, sample]);
                      }
                    }}
                  >
                    {sample}
                  </button>
                ))}
              </div>
            ) : null}
            {!vbapOnDisk && (
              <p className="input-mode-note warn">
                <code>vbap.csv</code> / <code>vbap.xlsx</code> is not available on the shared drive yet.
              </p>
            )}
          </div>
        )}

        {inputMode === "erdat" && (
          <div className="erdat-input-panel">
            <label className="erdat-input-label" htmlFor="erdat-picker">
              VBAP.ERDAT — order creation date
            </label>
            <p className="erdat-input-hint">
              Select the SAP creation date to filter rows from the shared drive VBAP
              export (stored as YYYYMMDD).
            </p>
            <div className="erdat-picker-row">
              <input
                id="erdat-picker"
                type="date"
                className="erdat-date-input"
                value={sapErdatToIso(erdat)}
                onChange={(e) => onErdatChange(isoToSapErdat(e.target.value))}
              />
              {erdat && (
                <span className="erdat-sap-display">
                  SAP format: <code>{erdat}</code>
                </span>
              )}
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => onErdatChange("")}
                disabled={!erdat}
              >
                Clear
              </button>
            </div>
            {!preview?.has_erdat_column && vbapInMemory && (
              <p className="input-mode-note warn">
                Shared drive <code>vbap.csv</code> has no ERDAT column.
              </p>
            )}
          </div>
        )}
      </div>

      <div className={`scope-preview-card ${previewLoading ? "loading" : ""}`}>
        <div className="scope-preview-header">
          <h3>Scope preview</h3>
          {previewLoading && <span className="scope-preview-spinner" aria-hidden />}
        </div>
        {preview ? (
          <>
            <p className="scope-preview-message">{preview.message}</p>
            <div className="scope-preview-stats">
              <div className="scope-stat">
                <span className="scope-stat-value">{preview.matching_rows}</span>
                <span className="scope-stat-label">VBAP lines in scope</span>
              </div>
              <div className="scope-stat">
                <span className="scope-stat-value">{preview.matching_orders}</span>
                <span className="scope-stat-label">Unique orders</span>
              </div>
              <div className="scope-stat">
                <span className="scope-stat-value">{preview.commodity_relevant_total}</span>
                <span className="scope-stat-label">Total in dataset</span>
              </div>
            </div>
            {preview.unknown_vbelns.length > 0 && (
              <p className="scope-preview-warn">
                Not found in shared drive VBAP:{" "}
                {preview.unknown_vbelns.map((v, i) => (
                  <span key={v}>
                    <code>{v}</code>
                    {i < preview.unknown_vbelns.length - 1 ? ", " : ""}
                  </span>
                ))}
              </p>
            )}
          </>
        ) : (
          <p className="muted">Load data to see scope preview.</p>
        )}
      </div>

      <div className="upload-data-section">
        <button
          type="button"
          className="upload-data-toggle"
          onClick={() => setShowDataFiles((v) => !v)}
          aria-expanded={showDataFiles}
          aria-controls="data-files-panel"
        >
          <span className="shared-files-heading">
            Data files ({memoryLoadedCount}/{EXPECTED_UPLOAD_FILES.length})
            {!dataReady && allOnDisk && (
              <span className="upload-data-toggle-hint"> — reload required</span>
            )}
            {!allOnDisk && (
              <span className="upload-data-toggle-hint"> — {missingFiles.length} missing</span>
            )}
          </span>
          <span className="upload-data-chevron" aria-hidden>
            {showDataFiles ? "▾" : "▸"}
          </span>
        </button>
        {showDataFiles && (
          <div id="data-files-panel" className="upload-table-wrap">
            <table className="upload-status-table">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">SAP table</th>
                <th scope="col">File</th>
                <th scope="col">Status</th>
                <th scope="col">Source</th>
                <th scope="col">Rows</th>
                <th scope="col">Columns</th>
                <th scope="col">Size</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const stats = row.stats;
                const onDisk = stats?.loaded ?? false;
                const inMemory = dataReady && onDisk;
                return (
                  <tr
                    key={row.filename}
                    className={
                      inMemory ? "row-loaded" : onDisk ? "row-unloaded" : "row-missing"
                    }
                  >
                    <td>{row.index}</td>
                    <td>
                      <span className="upload-table-label">{row.label}</span>
                      <span className="upload-table-desc">{row.description}</span>
                    </td>
                    <td>
                      <code className="upload-filename">
                        {stats?.resolved_filename &&
                        stats.resolved_filename !== row.filename
                          ? stats.resolved_filename
                          : formatHintForTable(row.filename)}
                      </code>
                    </td>
                    <td>
                      {inMemory ? (
                        <span className="upload-status upload-status-ok">Loaded</span>
                      ) : onDisk ? (
                        <span className="upload-status upload-status-pending">Not loaded</span>
                      ) : (
                        <span className="upload-status upload-status-missing">Missing</span>
                      )}
                    </td>
                    <td>{inMemory && stats ? sourceLabel(stats.source) : "—"}</td>
                    <td>{inMemory && stats ? stats.row_count.toLocaleString() : "—"}</td>
                    <td>{inMemory && stats ? stats.column_count : "—"}</td>
                    <td>
                      {inMemory && stats ? formatBytes(stats.file_size_bytes) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        )}
      </div>
    </section>
  );
}
