interface Props {
  phase: number;
  inline?: boolean;
}

const PHASES = [
  "Loading SAP table data…",
  "Matching VBAP ↔ CMM_VLOGP…",
  "Running qRFC & change research…",
  "Running AI agents…",
  "Building PDF report…",
];

export default function AnalysisProgressPanel({ phase, inline = false }: Props) {
  if (inline) {
    return (
      <section className="step-panel progress-step-panel" role="status" aria-live="polite">
        <div className="step-panel-header">
          <span className="step-badge">Step 4</span>
          <h2>Analysis in progress</h2>
          <p>
            Reconciling records, researching qRFC and change documents, and running OpenAI agents.
            Most of the wait is AI analysis — PDF generation is typically under one second.
          </p>
        </div>

        <div className="progress-inline-card">
          <div className="loading-rings progress-rings" aria-hidden>
            <span />
            <span />
          </div>
          <ul className="loading-phases progress-phases">
            {PHASES.map((label, i) => (
              <li key={label} className={i <= phase ? "active" : ""}>
                <span className="phase-dot" />
                {label}
              </li>
            ))}
          </ul>
        </div>
      </section>
    );
  }

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
