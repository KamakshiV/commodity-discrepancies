import type { LlmConfigResponse } from "../types";
import { FALLBACK_LLM_MODELS } from "../constants/llmModels";

interface Props {
  useAi: boolean;
  onUseAiChange: (v: boolean) => void;
  generatePdf: boolean;
  onGeneratePdfChange: (v: boolean) => void;
  llmConfig: LlmConfigResponse | null;
  llmModel: string;
  onLlmModelChange: (model: string) => void;
  onAnalyze: () => void;
  onDownloadPdf?: () => void;
  loading: boolean;
  canAnalyze: boolean;
  pdfReady: boolean;
  visible: boolean;
}

export default function ConfigPanel({
  useAi,
  onUseAiChange,
  generatePdf,
  onGeneratePdfChange,
  llmConfig,
  llmModel,
  onLlmModelChange,
  onAnalyze,
  onDownloadPdf,
  loading,
  canAnalyze,
  pdfReady,
  visible,
}: Props) {
  if (!visible) return null;

  const models = llmConfig?.models?.length ? llmConfig.models : FALLBACK_LLM_MODELS;
  const aiConfigured = llmConfig?.ai_configured ?? false;

  return (
    <aside className="config-panel">
      <h2 className="panel-title">Analysis settings</h2>

      <div className="agents-card">
        <label className="switch-row">
          <span className="switch-label">
            <strong>OpenAI agents</strong>
            <small>Explain root causes &amp; narrative</small>
          </span>
          <input
            type="checkbox"
            className="switch-input"
            checked={useAi}
            onChange={(e) => onUseAiChange(e.target.checked)}
          />
          <span className="switch-ui" aria-hidden />
        </label>

        {useAi && (
          <div className="agents-model-panel" role="group" aria-label="LLM model selection">
            <label className="field-label" htmlFor="llm-model">
              Select LLM model
            </label>
            <select
              id="llm-model"
              className="field-select"
              value={llmModel || models[0]?.id}
              disabled={loading}
              onChange={(e) => onLlmModelChange(e.target.value)}
            >
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>

            <div className="model-chips" role="listbox" aria-label="Quick model pick">
              {models.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  role="option"
                  aria-selected={llmModel === m.id}
                  className={`model-chip ${llmModel === m.id ? "selected" : ""}`}
                  disabled={loading}
                  onClick={() => onLlmModelChange(m.id)}
                >
                  {m.label}
                </button>
              ))}
            </div>

            {!aiConfigured && (
              <p className="field-hint warn">
                Add <code>OPENAI_API_KEY</code> in backend/.env to enable live agents.
              </p>
            )}
            {aiConfigured && (
              <p className="field-hint ok">
                API connected · selected: <strong>{llmModel}</strong>
              </p>
            )}
          </div>
        )}
      </div>

      <div className="toggle-card">
        <label className="switch-row">
          <span className="switch-label">
            <strong>PDF report</strong>
            <small>Auto-download after analysis</small>
          </span>
          <input
            type="checkbox"
            className="switch-input"
            checked={generatePdf}
            onChange={(e) => onGeneratePdfChange(e.target.checked)}
          />
          <span className="switch-ui" aria-hidden />
        </label>
      </div>

      <div className="config-actions">
        <button
          type="button"
          className="btn btn-primary btn-block"
          onClick={onAnalyze}
          disabled={loading || !canAnalyze}
        >
          {loading ? (
            <>
              <span className="spinner" aria-hidden />
              Running analysis…
            </>
          ) : (
            <>Run analysis</>
          )}
        </button>

        {pdfReady && onDownloadPdf && (
          <button
            type="button"
            className="btn btn-secondary btn-block"
            disabled={loading}
            onClick={onDownloadPdf}
          >
            Download PDF again
          </button>
        )}
      </div>
    </aside>
  );
}
