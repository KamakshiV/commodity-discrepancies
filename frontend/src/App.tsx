import { useCallback, useEffect, useMemo, useState } from "react";
import AppFooter from "./components/AppFooter";
import AnalysisProgressPanel from "./components/AnalysisProgressPanel";
import AttributeMappingPanel, {
  clearSavedMappings,
  loadSavedMappings,
  saveMappings,
} from "./components/AttributeMappingPanel";
import ModelSelectionPanel from "./components/ModelSelectionPanel";
import ResultsDashboard from "./components/ResultsDashboard";
import UploadPanel from "./components/UploadPanel";
import Breadcrumbs, { STEP_ORDER, type AppStep } from "./components/Breadcrumbs";
import { DEFAULT_LLM_MODEL, FALLBACK_LLM_MODELS } from "./constants/llmModels";
import { EXPECTED_UPLOAD_FILES, resolveUploadFilename } from "./constants/uploadFiles";
import type {
  AnalysisResult,
  AttributeMapping,
  CompareFieldsResponse,
  FileUploadStats,
  HealthResponse,
  LlmConfigResponse,
} from "./types";
import {
  fetchCompareFields,
  fetchFileStats,
  fetchHealth,
  downloadPdfReport,
  fetchLlmConfig,
  runAnalysis,
  clearUploadedFiles,
  uploadCsvFiles,
} from "./services/api";
import "./App.css";

const LLM_MODEL_STORAGE_KEY = "commodity_llm_model";

function statsMap(files: FileUploadStats[]): Record<string, FileUploadStats> {
  return Object.fromEntries(files.map((f) => [f.filename, f]));
}

function deriveStep(result: AnalysisResult | null, workflowStep: AppStep): AppStep {
  if (result) return "results";
  return workflowStep;
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [loadingPhase, setLoadingPhase] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [useAi, setUseAi] = useState(true);
  const [llmConfig, setLlmConfig] = useState<LlmConfigResponse | null>(null);
  const [llmModel, setLlmModel] = useState(DEFAULT_LLM_MODEL);
  const [compareFields, setCompareFields] = useState<CompareFieldsResponse | null>(null);
  const [mappings, setMappings] = useState<AttributeMapping[]>([]);
  const [pdfMessage, setPdfMessage] = useState<string | null>(null);
  const [workflowStep, setWorkflowStep] = useState<AppStep>("upload");
  const [fileStats, setFileStats] = useState<Record<string, FileUploadStats>>({});
  const [uploading, setUploading] = useState(false);
  const [maxReachableStep, setMaxReachableStep] = useState<AppStep>("upload");

  const activeMappings = mappings.filter((m) => m.enabled && m.vbap_field && m.cmm_field);
  const allFilesLoaded = EXPECTED_UPLOAD_FILES.every(
    (f) => fileStats[f.filename]?.loaded
  );
  const canAnalyze = activeMappings.length > 0 && !!health && allFilesLoaded;
  const currentStep = deriveStep(result, workflowStep);

  const loadLlmConfig = useCallback(async () => {
    try {
      const config = await fetchLlmConfig();
      setLlmConfig(config);
      const saved = localStorage.getItem(LLM_MODEL_STORAGE_KEY);
      const initial =
        saved && config.models.some((m) => m.id === saved)
          ? saved
          : config.default_model;
      setLlmModel(initial);
    } catch {
      setLlmConfig(null);
      const saved = localStorage.getItem(LLM_MODEL_STORAGE_KEY);
      if (saved && FALLBACK_LLM_MODELS.some((m) => m.id === saved)) {
        setLlmModel(saved);
      }
    }
  }, []);

  const loadCompareFields = useCallback(async () => {
    try {
      const fields = await fetchCompareFields();
      setCompareFields(fields);
      setMappings((prev) =>
        prev.length ? prev : loadSavedMappings(fields.default_mappings)
      );
    } catch {
      setCompareFields(null);
    }
  }, []);

  const loadFileStats = useCallback(async () => {
    try {
      const response = await fetchFileStats();
      setFileStats(statsMap(response.files));
    } catch {
      setFileStats({});
    }
  }, []);

  const loadHealth = useCallback(async () => {
    try {
      setHealth(await fetchHealth());
      await Promise.all([loadCompareFields(), loadLlmConfig(), loadFileStats()]);
    } catch {
      setHealth(null);
    }
  }, [loadCompareFields, loadLlmConfig, loadFileStats]);

  useEffect(() => {
    loadHealth();
  }, [loadHealth]);

  useEffect(() => {
    if (!analyzing) {
      setLoadingPhase(0);
      return;
    }
    const id = setInterval(() => {
      setLoadingPhase((p) => Math.min(p + 1, 4));
    }, 2200);
    return () => clearInterval(id);
  }, [analyzing]);

  useEffect(() => {
    if (allFilesLoaded) {
      setMaxReachableStep((prev) =>
        STEP_ORDER.indexOf(prev) < STEP_ORDER.indexOf("mapping") ? "mapping" : prev
      );
    }
  }, [allFilesLoaded]);

  useEffect(() => {
    if (canAnalyze) {
      setMaxReachableStep((prev) =>
        STEP_ORDER.indexOf(prev) < STEP_ORDER.indexOf("model") ? "model" : prev
      );
    }
  }, [canAnalyze]);

  useEffect(() => {
    if (result) {
      setMaxReachableStep("results");
    }
  }, [result]);

  const tableChips = useMemo(() => health?.tables_loaded ?? [], [health]);

  const handleMappingsChange = (next: AttributeMapping[]) => {
    setMappings(next);
    saveMappings(next);
  };

  const handleResetMappings = () => {
    if (!compareFields) return;
    const defaults = compareFields.default_mappings.map((m) => ({ ...m }));
    setMappings(defaults);
    saveMappings(defaults);
  };

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setError(null);
    setWorkflowStep("progress");
    try {
      if (activeMappings.length === 0) {
        setError("Enable at least one attribute mapping before running analysis.");
        setWorkflowStep("mapping");
        setAnalyzing(false);
        return;
      }
      setPdfMessage(null);
      const data = await runAnalysis(useAi, mappings, llmModel, true);
      setResult(data);
      setWorkflowStep("results");
      if (data.pdf_available) {
        await downloadPdfReport();
        setPdfMessage("PDF report downloaded successfully.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
      setWorkflowStep("model");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleUploadFiles = async (files: File[]) => {
    const unknown: string[] = [];
    const byName = new Map<string, File>();

    for (const file of files) {
      const canonical = resolveUploadFilename(file.name);
      if (!canonical) {
        if (file.name.toLowerCase().endsWith(".csv")) {
          unknown.push(file.name);
        }
        continue;
      }
      byName.set(
        canonical,
        file.name.toLowerCase() === canonical
          ? file
          : new File([file], canonical, { type: file.type || "text/csv" })
      );
    }

    if (unknown.length) {
      setError(
        `Unrecognized file(s): ${unknown.join(", ")}. ` +
          "Name each export to start with its table (e.g. VBAP_*.csv, CMM_VLOGP_*.csv) " +
          `or use: ${EXPECTED_UPLOAD_FILES.map((f) => f.filename).join(", ")}`
      );
    }

    const toUpload = [...byName.values()];
    if (!toUpload.length) return;

    setUploading(true);
    if (!unknown.length) setError(null);
    try {
      await uploadCsvFiles(toUpload);
      await loadHealth();
      const stats = await fetchFileStats();
      setFileStats(statsMap(stats.files));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const goToStep = (step: AppStep) => {
    if (step === "progress") return;
    if (result && step !== "results") {
      setResult(null);
      setPdfMessage(null);
    }
    setWorkflowStep(step);
  };

  const handleStartOver = async () => {
    if (analyzing) return;
    const confirmed = window.confirm(
      "Start over? This clears your analysis, deletes all uploaded CSV files from the server, and returns to step 1."
    );
    if (!confirmed) return;

    setResult(null);
    setError(null);
    setPdfMessage(null);
    setAnalyzing(false);
    setLoadingPhase(0);
    setWorkflowStep("upload");
    setMaxReachableStep("upload");
    setUploading(false);
    clearSavedMappings();

    try {
      const cleared = await clearUploadedFiles();
      setFileStats(statsMap(cleared.file_stats));
      setHealth(await fetchHealth());
      const fields = await fetchCompareFields();
      setCompareFields(fields);
      setMappings(fields.default_mappings.map((m) => ({ ...m })));
      await loadLlmConfig();
    } catch (err) {
      setHealth(null);
      setCompareFields(null);
      setMappings([]);
      setFileStats({});
      setError(err instanceof Error ? err.message : "Failed to reset session");
    }

    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleDownloadPdf = async () => {
    try {
      await downloadPdfReport();
      setPdfMessage("PDF report downloaded.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "PDF download failed");
    }
  };

  return (
    <div className="app-shell">
      <header className="hero">
        <div className="hero-text">
          <p className="hero-eyebrow">Turiaixis · SAP Commodity Intelligence</p>
          <h1>Commodity Discrepancy Analysis</h1>
          <p className="hero-subtitle">
            Reconcile VBAP with CMM_VLOGP using deterministic rules, then let AI
            explain root causes and deliver a PDF report.
          </p>
        </div>
        {health && (
          <div className="hero-status">
            <span className={`status-pill ${health.status === "ok" ? "ok" : ""}`}>
              ● {health.status}
            </span>
            <div className="table-chips">
              {tableChips.map((t) => (
                <span key={t} className="chip chip-table">
                  {t}
                </span>
              ))}
            </div>
          </div>
        )}
      </header>

      <div className="app">
        <div className="workflow-toolbar">
          <Breadcrumbs
            current={currentStep}
            onNavigate={goToStep}
            maxReachableStep={maxReachableStep}
          />
          <button
            type="button"
            className="btn btn-outline btn-start-over"
            onClick={handleStartOver}
            disabled={analyzing || uploading}
            title="Clear analysis, delete uploaded files, and return to upload step"
          >
            Start over
          </button>
        </div>

        {error && (
          <div className="toast toast-error" role="alert">
            {error}
            <button type="button" className="toast-close" onClick={() => setError(null)}>
              ×
            </button>
          </div>
        )}
        {pdfMessage && !error && (
          <div className="toast toast-success" role="status">
            {pdfMessage}
            <button type="button" className="toast-close" onClick={() => setPdfMessage(null)}>
              ×
            </button>
          </div>
        )}

        <div className="workspace workspace-single">
          <main className="workspace-main">
            {currentStep === "upload" && !result && (
              <UploadPanel
                fileStats={fileStats}
                uploading={uploading}
                onUploadFiles={handleUploadFiles}
                onContinue={() => goToStep("mapping")}
              />
            )}

            {currentStep === "mapping" && !result && (
              <section className="step-panel mapping-step-panel">
                <div className="step-panel-header">
                  <span className="step-badge">Step 2</span>
                  <h2>Select field attributes</h2>
                  <p>
                    Map VBAP columns to CMM_VLOGP fields used to identify mismatches.
                    Enable the attributes you want compared during reconciliation.
                  </p>
                </div>
                <AttributeMappingPanel
                  fields={compareFields}
                  mappings={mappings}
                  onChange={handleMappingsChange}
                  onReset={handleResetMappings}
                />
                <div className="step-panel-actions">
                  <button type="button" className="btn btn-outline" onClick={() => goToStep("upload")}>
                    Back to upload
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => goToStep("model")}
                    disabled={!canAnalyze}
                  >
                    Continue to model selection
                  </button>
                </div>
              </section>
            )}

            {currentStep === "model" && !result && (
              <ModelSelectionPanel
                llmConfig={llmConfig}
                llmModel={llmModel}
                useAi={useAi}
                onUseAiChange={setUseAi}
                onLlmModelChange={(m) => {
                  setLlmModel(m);
                  localStorage.setItem(LLM_MODEL_STORAGE_KEY, m);
                }}
                onContinue={handleAnalyze}
                onBack={() => goToStep("mapping")}
              />
            )}

            {currentStep === "progress" && !result && (
              <AnalysisProgressPanel phase={loadingPhase} inline />
            )}

            {currentStep === "results" && result && (
              <section className="step-panel results-step-panel">
                <div className="step-panel-header results-step-header">
                  <div>
                    <span className="step-badge">Step 5</span>
                    <h2>Analysis results</h2>
                    <p>
                      Review discrepancies, AI insights, and recommended actions. Download
                      the PDF report for sharing with operations teams.
                    </p>
                  </div>
                  {result.pdf_available && (
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={handleDownloadPdf}
                    >
                      Download PDF report
                    </button>
                  )}
                </div>
                <ResultsDashboard result={result} />
              </section>
            )}
          </main>
        </div>
      </div>

      <AppFooter />
    </div>
  );
}
