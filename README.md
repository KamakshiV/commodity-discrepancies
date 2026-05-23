# Commodity Discrepancy Analysis (POC)

AI-powered application to identify **VBAP vs CMM_VLOGP** commodity discrepancies, research root causes, and generate PDF reports.

## Architecture

| Layer | Responsibility |
|-------|----------------|
| **Rule engine** (Python/pandas) | Deterministic: missing records, attribute mismatches, qRFC/CDPOS lookups |
| **CrewAI agents** (OpenAI) | Explain, classify, summarize, recommend actions, write PDF narrative |
| **React UI** | Run analysis, view results, upload CSVs, download PDF |

**Principle:** AI never decides whether a discrepancy exists — only explains and recommends.

## Tech stack

- **Backend:** FastAPI, pandas, OpenAI SDK (agent prompts), ReportLab
- **Frontend:** React + Vite + TypeScript
- **Data (POC):** CSV files in `backend/data/sample/`
- **Future:** Live SAP connector (replace `DataStore`)

## Quick start

### 1. Backend

macOS often has `python3` but not `python`. **Run one command per line** (do not paste comment lines starting with `#`).

**Easy start** (from project folder):

```bash
cd backend
bash start.sh
```

**Manual start:**

```bash
cd "/Users/kamakshi/Documents/AgenticAI-IK/Commodity Discrepancies Analysis/backend"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-ai.txt
cp .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```

If your prompt already shows `backend %`, **do not** run `cd backend` again.

Edit `backend/.env` and set `OPENAI_API_KEY=sk-...` (and optional `OPENAI_MODEL` / `OPENAI_MODELS`).

The app runs **without** AI packages: rule engine, mapping UI, and PDF work; toggle off **Use OpenAI agents** or add `OPENAI_API_KEY` after installing `requirements-ai.txt`.

API docs: http://localhost:8000/docs

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

UI: http://localhost:5173

### 3. Run analysis

1. Open the UI (sample CSVs load automatically).
2. Configure **Attribute Comparison Mapping** — parallel VBAP ↔ CMM_VLOGP field rows (add/remove, enable/disable).
3. Toggle **Use OpenAI agents** (requires API key; otherwise rule-engine fallback).
4. Ensure **Generate PDF output** is checked (default on).
5. Click **Run Analysis** — the PDF downloads automatically when complete.
6. Use **Download PDF again** to re-fetch the latest report.

Mappings are saved in browser localStorage and sent to the API on each run.

## Sample data scenarios

| VBELN/POSNR | Scenario |
|-------------|----------|
| 8000001003/10 | Missing in CMM_VLOGP + qRFC error |
| 8000001006/10 | Missing in CMM_VLOGP + qRFC error |
| 8000001002/10 | Attribute mismatch (quantity) + CDPOS change |
| 8000001005/10 | Attribute mismatch (unit) + CDPOS change |

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Service health + loaded tables |
| POST | `/api/analyze?use_ai=true` | Run full analysis |
| GET | `/api/report/pdf` | Download PDF (run analyze first) |
| POST | `/api/data/upload` | Upload CSV files |
| GET | `/api/data/tables` | Row counts per table |
| GET | `/api/config/llm` | OpenAI model dropdown options + default |
| GET | `/api/data/compare-fields` | VBAP/CMM columns + default mappings |
| POST | `/api/analyze` (JSON body) | Optional `compare_mappings` array |

## CSV file names (upload)

- `vbap.csv`
- `cmm_vlogp.csv`
- `qrfc_i_qin_top.csv`
- `qrfc_i_err_state.csv`
- `cdhdr.csv`
- `cdpos.csv`

## AI agent steps (OpenAI)

1. Discrepancy Classifier  
2. qRFC Investigator  
3. Change History Investigator  
4. Root Cause Summarizer  
5. Action Recommendation Specialist  
6. PDF Report Writer (on PDF generation)

## Deployment (Vercel + Render)

| Service | URL / notes |
|---------|-------------|
| **Backend (Render)** | `https://commodity-discrepancies.onrender.com` — start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| **Health check** | `/api/health` (not `/`) |
| **Frontend (Vercel)** | Root directory: `frontend` — `vercel.json` proxies `/api/*` to Render |

**Render environment variables**

- `OPENAI_API_KEY` — required for AI steps
- `CORS_ORIGINS` — only needed if the frontend calls Render **directly** via `VITE_API_URL` (comma-separated Vercel URL + localhost)
- Optional `UPLOAD_DIR` — writable path if the default upload folder fails

**Vercel**

- Redeploy after pulling `frontend/vercel.json` so uploads hit Render instead of a non-existent `/api` on Vercel.
- Optional: `VITE_API_URL=https://commodity-discrepancies.onrender.com` (host only is fine; `/api` is appended in the app). Set `CORS_ORIGINS` on Render to your Vercel origin.

**Upload fails after deploy?**

1. Browser Network tab: upload should go to `…/api/data/upload` on your Vercel app (proxied) or to Render if `VITE_API_URL` is set.
2. If you see **404 HTML** from Vercel, redeploy with `vercel.json` or set `VITE_API_URL`.
3. If you see **CORS** errors, add your Vercel URL to `CORS_ORIGINS` on Render.
4. Render **free tier** disk is ephemeral — uploads are cleared on redeploy.

## Troubleshooting

| Error | Fix |
|-------|-----|
| Upload / API 404 on Vercel | Add `frontend/vercel.json` or set `VITE_API_URL` to Render `/api` and redeploy |
| CORS blocked on upload | Set `CORS_ORIGINS=https://your-app.vercel.app,http://localhost:5173` on Render |
| `command not found: python` | Use `python3` to create the venv; after `source .venv/bin/activate`, `python` works inside the venv |
| `unsupported operand type(s) for \|` | Caused by old **CrewAI on Python 3.9** — reinstall AI deps: `pip install -r requirements-ai.txt` (OpenAI SDK only, no CrewAI) |
| `No matching distribution found for crewai>=0.86` | Use `requirements-ai.txt` (OpenAI only) or `requirements-ai-py310.txt` if you want CrewAI on Python 3.10+ |
| `cd: no such file or directory: backend` | You are already inside `backend` — skip `cd backend` and run `bash start.sh` or uvicorn directly |
| `[Errno 48] Address already in use` | `pkill -f "uvicorn app.main:app"` or `lsof -i :8000` then `kill <PID>`; `start.sh` does this automatically |
| `zsh: command not found: #` | Paste commands **one line at a time**; don’t paste comment lines with `#` as commands |
| `command not found: python` | Use `python3` before venv exists; after `source .venv/bin/activate`, use `python` |

## Migrating to live SAP

Replace `DataStore.load_all()` with an SAP RFC/OData client that returns the same DataFrame schemas. The rule engine and agents remain unchanged.
