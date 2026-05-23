export type AppStep = "upload" | "mapping" | "model" | "progress" | "results";

interface Crumb {
  id: AppStep;
  label: string;
}

const CRUMBS: Crumb[] = [
  { id: "upload", label: "Select data" },
  { id: "mapping", label: "Select attributes" },
  { id: "model", label: "OpenAI model" },
  { id: "progress", label: "Analysis" },
  { id: "results", label: "Results" },
];

interface Props {
  current: AppStep;
  onNavigate?: (step: AppStep) => void;
  maxReachableStep?: AppStep;
}

const STEP_ORDER: AppStep[] = ["upload", "mapping", "model", "progress", "results"];

function stepIndex(step: AppStep): number {
  return STEP_ORDER.indexOf(step);
}

export default function Breadcrumbs({ current, onNavigate, maxReachableStep }: Props) {
  const currentIdx = stepIndex(current);
  const maxIdx = maxReachableStep ? stepIndex(maxReachableStep) : currentIdx;

  return (
    <nav className="chevron-breadcrumb" aria-label="Analysis workflow">
      <ol className="chevron-trail chevron-trail-five">
        {CRUMBS.map((crumb, idx) => {
          const done = idx < currentIdx;
          const active = crumb.id === current;
          const isFirst = idx === 0;
          const isLast = idx === CRUMBS.length - 1;
          const canNavigate = onNavigate && idx <= maxIdx && crumb.id !== "progress";

          return (
            <li
              key={crumb.id}
              className={[
                "chevron-step",
                isFirst && "first",
                isLast && "last",
                done && "done",
                active && "active",
                !done && !active && "upcoming",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              <button
                type="button"
                className="chevron-step-btn"
                onClick={() => canNavigate && onNavigate?.(crumb.id)}
                disabled={!canNavigate}
                aria-current={active ? "step" : undefined}
              >
                <span
                  className={[
                    "chevron-icon",
                    done && "complete",
                    active && "current",
                    !done && !active && "pending",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  aria-hidden="true"
                >
                  {done ? (
                    <svg viewBox="0 0 12 12" width="12" height="12" fill="none">
                      <path
                        d="M2 6l3 3 5-5"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  ) : (
                    <span className="chevron-dot" />
                  )}
                </span>
                <span className="chevron-label">{crumb.label}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export { STEP_ORDER };
