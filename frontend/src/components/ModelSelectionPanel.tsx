import type { LlmConfigResponse } from "../types";
import { FALLBACK_LLM_MODELS } from "../constants/llmModels";

interface Props {
  llmConfig: LlmConfigResponse | null;
  llmModel: string;
  useAi: boolean;
  onUseAiChange: (v: boolean) => void;
  onLlmModelChange: (model: string) => void;
  onContinue: () => void;
  onBack: () => void;
}

export default function ModelSelectionPanel({
  llmConfig,
  llmModel,
  useAi,
  onUseAiChange,
  onLlmModelChange,
  onContinue,
  onBack,
}: Props) {
  const models = llmConfig?.models?.length ? llmConfig.models : FALLBACK_LLM_MODELS;
  const aiConfigured = llmConfig?.ai_configured ?? false;

  return (
    <section className="step-panel model-step-panel">
      <div className="step-panel-header">
        <span className="step-badge">Step 3</span>
        <h2>Select OpenAI model</h2>
        <p>
          Choose the LLM used by investigation agents for root-cause analysis and narrative generation in the PDF report.
        </p>
      </div>

      <label className="switch-row model-toggle">
        <span className="switch-label">
          <strong>Enable OpenAI agents</strong>
          <small>Automated explanation and recommended actions</small>
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
        <div className="model-select-block">
          <label className="field-label" htmlFor="workflow-llm-model">
            LLM model
          </label>
          <select
            id="workflow-llm-model"
            className="field-select model-select-large"
            value={llmModel || models[0]?.id}
            onChange={(e) => onLlmModelChange(e.target.value)}
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>

          {!aiConfigured && (
            <p className="field-hint warn">
              Add <code>OPENAI_API_KEY</code> in backend/.env to enable live agents.
              Analysis will use rule-engine fallbacks without a key.
            </p>
          )}
          {aiConfigured && (
            <p className="field-hint ok">
              API connected · selected model: <strong>{llmModel}</strong>
            </p>
          )}
        </div>
      )}

      <div className="step-panel-actions">
        <button type="button" className="btn btn-outline" onClick={onBack}>
          Back to attributes
        </button>
        <button type="button" className="btn btn-primary" onClick={onContinue}>
          Start analysis
        </button>
      </div>
    </section>
  );
}
