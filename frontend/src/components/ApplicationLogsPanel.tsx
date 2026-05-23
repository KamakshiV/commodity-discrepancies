import { useMemo, useState } from "react";
import type { ApplicationLogEntry } from "../types";

interface Props {
  logs: ApplicationLogEntry[];
  aiTotalTokens?: number | null;
  compact?: boolean;
}

const STAGE_LABELS: Record<string, string> = {
  system: "System",
  api: "API",
  analysis: "Analysis",
  data_load: "Data load",
  rule_engine: "Rule engine",
  ai_agent: "AI agent",
  pdf: "PDF",
  upload: "Upload",
};

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso.slice(11, 19) || iso;
  }
}

function tokenSummary(log: ApplicationLogEntry): string | null {
  if (log.prompt_tokens == null && log.completion_tokens == null) return null;
  const parts: string[] = [];
  if (log.prompt_tokens != null) parts.push(`in ${log.prompt_tokens.toLocaleString()}`);
  if (log.completion_tokens != null) parts.push(`out ${log.completion_tokens.toLocaleString()}`);
  if (log.total_tokens != null) parts.push(`Σ ${log.total_tokens.toLocaleString()}`);
  return parts.join(" · ");
}

export default function ApplicationLogsPanel({
  logs,
  aiTotalTokens,
  compact = false,
}: Props) {
  const [expanded, setExpanded] = useState(!compact);
  const [filter, setFilter] = useState<"all" | "ai">("all");

  const aiCalls = useMemo(
    () => logs.filter((l) => l.level === "ai" && l.message.includes("finished")),
    [logs]
  );

  const displayed = useMemo(() => {
    if (filter === "ai") return logs.filter((l) => l.stage === "ai_agent" || l.level === "ai");
    return logs;
  }, [logs, filter]);

  if (!logs.length) {
    return (
      <p className="app-logs-empty">No application logs for this run.</p>
    );
  }

  return (
    <section className="app-logs-panel" aria-label="Application logs">
      <div className="app-logs-header">
        <div>
          <h3>Application logs</h3>
          <p className="app-logs-subtitle">
            Stage-by-stage trace from the server, including OpenAI agent calls and token usage.
          </p>
        </div>
        <div className="app-logs-header-actions">
          {aiTotalTokens != null && aiTotalTokens > 0 && (
            <span className="app-logs-token-chip">
              {aiTotalTokens.toLocaleString()} total AI tokens
            </span>
          )}
          {aiCalls.length > 0 && (
            <span className="app-logs-meta">{aiCalls.length} agent call(s)</span>
          )}
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={() => setExpanded((e) => !e)}
          >
            {expanded ? "Collapse" : "Expand"}
          </button>
        </div>
      </div>

      {expanded && (
        <>
          <div className="app-logs-toolbar">
            <button
              type="button"
              className={`app-logs-filter ${filter === "all" ? "active" : ""}`}
              onClick={() => setFilter("all")}
            >
              All ({logs.length})
            </button>
            <button
              type="button"
              className={`app-logs-filter ${filter === "ai" ? "active" : ""}`}
              onClick={() => setFilter("ai")}
            >
              AI agents only
            </button>
          </div>

          <ol className="app-logs-list">
            {displayed.map((log, i) => (
              <li
                key={`${log.timestamp}-${i}`}
                className={`app-log-entry level-${log.level} stage-${log.stage}`}
              >
                <div className="app-log-line">
                  <time dateTime={log.timestamp}>{formatTime(log.timestamp)}</time>
                  <span className="app-log-stage">
                    {STAGE_LABELS[log.stage] ?? log.stage}
                  </span>
                  <span className={`app-log-level level-${log.level}`}>{log.level}</span>
                  {log.duration_ms != null && (
                    <span className="app-log-duration">{log.duration_ms.toFixed(0)} ms</span>
                  )}
                </div>
                <p className="app-log-message">{log.message}</p>
                {log.agent_name && (
                  <p className="app-log-meta">
                    Agent: <strong>{log.agent_name}</strong>
                    {log.model && <> · Model: {log.model}</>}
                  </p>
                )}
                {tokenSummary(log) && (
                  <p className="app-log-tokens">{tokenSummary(log)}</p>
                )}
                {log.detail && (
                  <pre className="app-log-detail">{log.detail}</pre>
                )}
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
