interface Props {
  phase: number;
}

const PHASES = [
  "Loading SAP table data…",
  "Matching VBAP ↔ CMM_VLOGP…",
  "Running qRFC & change research…",
  "Generating AI insights…",
  "Building PDF report…",
];

export default function LoadingOverlay({ phase }: Props) {
  return (
    <div className="loading-overlay" role="status" aria-live="polite">
      <div className="loading-card">
        <div className="loading-rings" aria-hidden>
          <span />
          <span />
        </div>
        <h3>Analyzing discrepancies</h3>
        <ul className="loading-phases">
          {PHASES.map((label, i) => (
            <li key={label} className={i <= phase ? "active" : ""}>
              <span className="phase-dot" />
              {label}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
