import { useCallback, useRef, useState } from "react";
import type { FileUploadStats } from "../types";
import { EXPECTED_UPLOAD_FILES } from "../constants/uploadFiles";

function formatBytes(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function pickCsvFiles(fileList: FileList | File[]): File[] {
  return Array.from(fileList).filter((f) =>
    f.name.toLowerCase().endsWith(".csv")
  );
}

interface Props {
  fileStats: Record<string, FileUploadStats>;
  uploading: boolean;
  onUploadFiles: (files: File[]) => void;
  onContinue: () => void;
}

export default function UploadPanel({
  fileStats,
  uploading,
  onUploadFiles,
  onContinue,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const rows = EXPECTED_UPLOAD_FILES.map((expected, idx) => ({
    ...expected,
    index: idx + 1,
    stats: fileStats[expected.filename],
  }));

  const loadedCount = rows.filter((r) => r.stats?.loaded).length;
  const allLoaded = loadedCount === EXPECTED_UPLOAD_FILES.length;
  const missingFiles = rows
    .filter((r) => !r.stats?.loaded)
    .map((r) => r.filename);

  const processFiles = useCallback(
    (incoming: FileList | File[]) => {
      const csvFiles = pickCsvFiles(incoming);
      if (csvFiles.length) onUploadFiles(csvFiles);
    },
    [onUploadFiles]
  );

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!uploading) setDragOver(true);
  };

  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    if (uploading) return;
    processFiles(e.dataTransfer.files);
  };

  return (
    <section className="step-panel upload-panel">
      <div className="step-panel-top">
        <div className="step-panel-header">
          <span className="step-badge">Step 1</span>
          <h2>Upload files</h2>
          <p>
            Drag and drop all six SAP export CSVs at once, or browse to select multiple
            files. Export names like <code>VBAP_May2025.csv</code> are recognized
            automatically. Status for each required table appears in the table below.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary step-panel-top-action"
          onClick={onContinue}
          disabled={!allLoaded || uploading}
        >
          Continue to attribute mapping
        </button>
      </div>

      <div
        className={`upload-dropzone ${dragOver ? "drag-over" : ""} ${uploading ? "disabled" : ""}`}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => !uploading && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            if (!uploading) inputRef.current?.click();
          }
        }}
        role="button"
        tabIndex={0}
        aria-disabled={uploading}
        aria-label="Upload SAP CSV files"
      >
        <span className="upload-dropzone-icon" aria-hidden>
          ↑
        </span>
        <span className="upload-dropzone-title">
          {uploading ? "Uploading files…" : "Drag & drop CSV files here"}
        </span>
        <span className="upload-dropzone-hint">
          or click to browse · SAP export names (e.g. VBAP_*.csv) are accepted
        </span>
        <span className="upload-dropzone-files">
          {EXPECTED_UPLOAD_FILES.map((f) => f.filename).join(" · ")}
        </span>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          multiple
          hidden
          disabled={uploading}
          onChange={(e) => {
            if (e.target.files?.length) processFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      <div className="upload-summary-bar" role="status">
        <span className="upload-summary-count">
          <strong>{loadedCount}</strong> of {EXPECTED_UPLOAD_FILES.length} files loaded
          {uploading && (
            <span className="upload-summary-uploading"> · Upload in progress…</span>
          )}
        </span>
        {allLoaded ? (
          <span className="upload-summary-ok">All required files are present.</span>
        ) : (
          <span className="upload-summary-missing">
            Missing: {missingFiles.join(", ")}
          </span>
        )}
      </div>

      {!allLoaded && missingFiles.length > 0 && (
        <div className="upload-missing-alert" role="alert">
          <strong>{missingFiles.length} required file(s) not loaded:</strong>{" "}
          {missingFiles.map((name, i) => (
            <span key={name}>
              <code>{name}</code>
              {i < missingFiles.length - 1 ? ", " : ""}
            </span>
          ))}
          . Upload the missing CSV(s) to continue.
        </div>
      )}

      <div className="upload-table-wrap">
        <table className="upload-status-table">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">SAP table</th>
              <th scope="col">Expected file</th>
              <th scope="col">Status</th>
              <th scope="col">Rows</th>
              <th scope="col">Columns</th>
              <th scope="col">Size</th>
              <th scope="col">Source</th>
              <th scope="col">Column preview</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const stats = row.stats;
              const loaded = stats?.loaded ?? false;
              return (
                <tr
                  key={row.filename}
                  className={loaded ? "row-loaded" : "row-missing"}
                >
                  <td>{row.index}</td>
                  <td>
                    <span className="upload-table-label">{row.label}</span>
                    <span className="upload-table-desc">{row.description}</span>
                  </td>
                  <td>
                    <code className="upload-filename">{row.filename}</code>
                  </td>
                  <td>
                    {loaded ? (
                      <span className="upload-status upload-status-ok">Loaded</span>
                    ) : (
                      <span className="upload-status upload-status-missing">Missing</span>
                    )}
                  </td>
                  <td>{loaded && stats ? stats.row_count.toLocaleString() : "—"}</td>
                  <td>{loaded && stats ? stats.column_count : "—"}</td>
                  <td>
                    {loaded && stats
                      ? formatBytes(stats.file_size_bytes)
                      : "—"}
                  </td>
                  <td>
                    {loaded && stats ? (
                      <span className="upload-source">{stats.source}</span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="upload-columns-cell">
                    {loaded && stats && stats.columns.length > 0 ? (
                      <>
                        {stats.columns.slice(0, 6).join(", ")}
                        {stats.columns.length > 6
                          ? ` +${stats.columns.length - 6} more`
                          : ""}
                      </>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
