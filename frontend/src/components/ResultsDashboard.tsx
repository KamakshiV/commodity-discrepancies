import { useMemo, useState } from "react";
import type { AgentInsight, AnalysisResult, DiscrepancyRecord } from "../types";

type ResultsTab = "overview" | "discrepancies" | "insights" | "actions";
type CategoryFilter = "all" | "missing" | "mismatch";

interface Props {
  result: AnalysisResult;
}

function isMissing(d: DiscrepancyRecord) {
  return d.category.includes("Missing");
}

export default function ResultsDashboard({ result }: Props) {
  const [tab, setTab] = useState<ResultsTab>("overview");
  const [filter, setFilter] = useState<CategoryFilter>("all");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const { summary, discrepancies, insights } = result;
  const total = summary.total_commodity_relevant || 1;

  const filtered = useMemo(() => {
    let list = discrepancies;
    if (filter === "missing") list = list.filter(isMissing);
    if (filter === "mismatch") list = list.filter((d) => !isMissing(d));
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (d) =>
          d.vbeln.toLowerCase().includes(q) ||
          d.posnr.toLowerCase().includes(q) ||
          d.category.toLowerCase().includes(q)
      );
    }
    return list;
  }, [discrepancies, filter, search]);

  const insightFor = (vbeln: string, posnr: string): AgentInsight | undefined =>
    insights.find((i) => i.vbeln === vbeln && i.posnr === posnr);

  const tabs: { id: ResultsTab; label: string; count?: number }[] = [
    { id: "overview", label: "Overview" },
    { id: "discrepancies", label: "Discrepancies", count: discrepancies.length },
    { id: "insights", label: "Insights", count: insights.length },
    { id: "actions", label: "Actions", count: summary.recommended_actions.length },
  ];

  return (
    <section className="results-dashboard animate-in">
      <div className="metrics-interactive">
        {[
          {
            label: "Commodity-relevant",
            value: summary.total_commodity_relevant,
            pct: 100,
            variant: "neutral",
          },
          {
            label: "Missing in CMM_VLOGP",
            value: summary.missing_count,
            pct: (summary.missing_count / total) * 100,
            variant: "danger",
          },
          {
            label: "Attribute mismatch",
            value: summary.mismatch_count,
            pct: (summary.mismatch_count / total) * 100,
            variant: "warn",
          },
          {
            label: "Clean records",
            value: summary.clean_count,
            pct: (summary.clean_count / total) * 100,
            variant: "ok",
          },
        ].map((m) => (
          <button
            key={m.label}
            type="button"
            className={`metric-card metric-${m.variant}`}
            onClick={() => {
              setTab("discrepancies");
              if (m.variant === "danger") setFilter("missing");
              else if (m.variant === "warn") setFilter("mismatch");
              else setFilter("all");
            }}
          >
            <span className="metric-card-value">{m.value}</span>
            <span className="metric-card-label">{m.label}</span>
            <span className="metric-bar">
              <span className="metric-bar-fill" style={{ width: `${Math.min(m.pct, 100)}%` }} />
            </span>
          </button>
        ))}
      </div>

      <div className="tab-bar" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`tab-btn ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.count !== undefined && t.count > 0 && (
              <span className="tab-count">{t.count}</span>
            )}
          </button>
        ))}
      </div>

      <div className="tab-panel" role="tabpanel">
        {tab === "overview" && (
          <div className="overview-panel">
            {result.ai_analysis_used && result.llm_model_used ? (
              <span className="chip chip-ai">AI analysis · {result.llm_model_used}</span>
            ) : (
              <span className="chip chip-rule">Rule-based analysis</span>
            )}
            {result.ai_total_tokens != null && result.ai_total_tokens > 0 && (
              <span className="chip chip-tokens">
                {result.ai_total_tokens.toLocaleString()} AI tokens
              </span>
            )}
            {summary.executive_summary && (
              <article className="insight-hero">
                <h3>Executive summary</h3>
                <p>{summary.executive_summary}</p>
              </article>
            )}
            {summary.root_cause_summary && (
              <article className="card-soft">
                <h3>Root cause summary</h3>
                <p>{summary.root_cause_summary}</p>
              </article>
            )}
            {!summary.executive_summary && !summary.root_cause_summary && (
              <p className="muted">Select a tab above to explore discrepancies and insights.</p>
            )}
          </div>
        )}

        {tab === "discrepancies" && (
          <div className="discrepancies-panel">
            <div className="toolbar">
              <input
                type="search"
                className="search-input"
                placeholder="Search VBELN, POSNR…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <div className="filter-chips">
                {(["all", "missing", "mismatch"] as CategoryFilter[]).map((f) => (
                  <button
                    key={f}
                    type="button"
                    className={`chip-btn ${filter === f ? "active" : ""}`}
                    onClick={() => setFilter(f)}
                  >
                    {f === "all" ? "All" : f === "missing" ? "Missing" : "Mismatch"}
                  </button>
                ))}
              </div>
            </div>
            <p className="toolbar-meta">
              Showing {filtered.length} of {discrepancies.length} records
            </p>
            <div className="discrepancy-list">
              {filtered.length === 0 && (
                <p className="muted empty-list">No records match your filters.</p>
              )}
              {filtered.map((d) => {
                const key = `${d.vbeln}-${d.posnr}`;
                const open = expanded === key;
                const ins = insightFor(d.vbeln, d.posnr);
                return (
                  <article
                    key={key}
                    className={`discrepancy-card ${open ? "open" : ""} ${isMissing(d) ? "type-missing" : "type-mismatch"}`}
                  >
                    <button
                      type="button"
                      className="discrepancy-card-header"
                      onClick={() => setExpanded(open ? null : key)}
                      aria-expanded={open}
                    >
                      <div className="dcard-id">
                        <span className="dcard-vbeln">{d.vbeln}</span>
                        <span className="dcard-posnr">/ {d.posnr}</span>
                      </div>
                      <span className={`badge ${isMissing(d) ? "missing" : "mismatch"}`}>
                        {d.category}
                      </span>
                      <span className="dcard-chevron" aria-hidden>
                        {open ? "▲" : "▼"}
                      </span>
                    </button>
                    {open && (
                      <div className="discrepancy-card-body">
                        {d.mismatched_fields?.length > 0 && (
                          <div className="detail-block">
                            <h4>Mismatched attributes</h4>
                            <ul>
                              {d.mismatched_fields.map((mf, i) => (
                                <li key={i}>{mf}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {Boolean(
                          d.qrf_research?.queue_matches &&
                            Array.isArray(d.qrf_research.queue_matches) &&
                            d.qrf_research.queue_matches.length > 0
                        ) && (
                          <div className="detail-block">
                            <h4>qRFC research</h4>
                            <pre className="detail-pre">
                              {JSON.stringify(d.qrf_research, null, 2)}
                            </pre>
                          </div>
                        )}
                        {d.change_history?.length > 0 && (
                          <div className="detail-block">
                            <h4>Change history (CDHDR → CDPOS)</h4>
                            <table className="change-history-table">
                              <thead>
                                <tr>
                                  <th>CHANGENR</th>
                                  <th>OBJECTID</th>
                                  <th>OBJECTCLASS</th>
                                  <th>TABNAME</th>
                                  <th>FNAME</th>
                                  <th>VALUE_OLD</th>
                                  <th>VALUE_NEW</th>
                                </tr>
                              </thead>
                              <tbody>
                                {d.change_history.map((ch, i) => (
                                  <tr key={i}>
                                    <td>{ch.CHANGENR ?? ch.changenr ?? "—"}</td>
                                    <td>{ch.OBJECTID ?? ch.objectid ?? "—"}</td>
                                    <td>{ch.OBJECTCLASS ?? ch.objectclass ?? "—"}</td>
                                    <td>{ch.TABNAME ?? ch.tabname ?? "—"}</td>
                                    <td>{ch.FNAME ?? ch.fname ?? "—"}</td>
                                    <td>{ch.VALUE_OLD ?? ch.value_old ?? "—"}</td>
                                    <td>{ch.VALUE_NEW ?? ch.value_new ?? "—"}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                        {ins && (
                          <div className="detail-block insight-inline">
                            <h4>{ins.agent_name}</h4>
                            {ins.likely_cause && <p className="cause">{ins.likely_cause}</p>}
                            {ins.recommended_action && (
                              <p className="action">
                                {ins.recommended_action}
                                {ins.recommended_owner && ` · ${ins.recommended_owner}`}
                              </p>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          </div>
        )}

        {tab === "insights" && (
          <div className="insights-grid">
            {insights.length === 0 && <p className="muted">No insights generated.</p>}
            {insights.map((ins, i) => (
              <article key={i} className="insight-card">
                <header>
                  <span className="insight-order">
                    {ins.vbeln}/{ins.posnr}
                  </span>
                  <span className="agent-pill">{ins.agent_name}</span>
                </header>
                {ins.classification && <p>{ins.classification}</p>}
                {ins.likely_cause && <p className="cause">{ins.likely_cause}</p>}
                {ins.recommended_action && (
                  <footer>
                    <span className="action">{ins.recommended_action}</span>
                    {ins.recommended_owner && (
                      <span className="owner">{ins.recommended_owner}</span>
                    )}
                  </footer>
                )}
              </article>
            ))}
          </div>
        )}

        {tab === "actions" && (
          <div className="actions-grid">
            {summary.recommended_actions.length === 0 && (
              <p className="muted">No recommended actions.</p>
            )}
            {summary.recommended_actions.map((a, i) => (
              <article key={i} className="action-card">
                <h4>{a.issue}</h4>
                <p className="action-owner">{a.recommended_owner}</p>
                <p>{a.action}</p>
              </article>
            ))}
          </div>
        )}

      </div>
    </section>
  );
}
