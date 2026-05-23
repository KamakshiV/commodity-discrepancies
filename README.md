# Commodity Discrepancy Analysis (POC)

AI-powered application to identify **VBAP vs CMM_VLOGP** commodity discrepancies, research root causes, and generate PDF reports.

## Architecture

| Layer | Responsibility |
|-------|----------------|
| **Rule engine** (Python/pandas) | Deterministic: missing records, attribute mismatches, qRFC/CDPOS lookups |
| **CrewAI agents** (OpenAI) | Explain, classify, summarize, recommend actions, write PDF narrative |
| **React UI** | Select data scope, run analysis, download PDF |

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
| POST | `/api/data/reload` | Reload CSVs from shared drive |
| POST | `/api/session/reset` | Reset analysis session |
| GET | `/api/data/scope-preview` | Preview VBELN/ERDAT scope |
| GET | `/api/data/tables` | Row counts per table |
| GET | `/api/config/llm` | OpenAI model dropdown options + default |
| GET | `/api/data/compare-fields` | VBAP/CMM columns + default mappings |
| POST | `/api/analyze` (JSON body) | Optional `compare_mappings` array |

## Data source (local folder or Google Drive)

The backend reads six SAP table exports (CSV or Excel). Configure via `DATA_SOURCE`:

### Option A — Local folder (default)

```env
DATA_SOURCE=local
SHARED_DATA_DIR=./data/sample
```

Place these files in that folder (CSV or Excel — `.csv`, `.xlsx`, or `.xls`):

- `vbap`, `cmm_vlogp`, `qrfc_i_qin_top`, `qrfc_i_err_state`, `cdhdr`, `cdpos`

SAP export names like `VBAP_May2025.csv` or `VBAP_May2025.xlsx` are also recognized.

### Option B — Google Drive (recommended for Render)

```env
DATA_SOURCE=google_drive
GOOGLE_DRIVE_FOLDER_ID=your-folder-id
SHARED_DATA_DIR=/tmp/commodity-data
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
```

**Setup steps**

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable **Google Drive API**.
2. Create a **Service Account** and download the JSON key.
3. Create a folder in Google Drive with the six SAP exports (CSV or Excel).
4. **Share the folder** with the service account email (`...@....iam.gserviceaccount.com`) as **Viewer**.
5. Copy the folder ID from the Drive URL: `https://drive.google.com/drive/folders/FOLDER_ID`
6. On Render, set env vars above. Paste the full service-account JSON into `GOOGLE_SERVICE_ACCOUNT_JSON` (single line), or use `GOOGLE_APPLICATION_CREDENTIALS` pointing to a mounted secret file.

On startup and when the UI clicks **Sync from Google Drive**, the backend downloads files into `SHARED_DATA_DIR` (local cache) and loads them from there.

No file upload in the UI — update files in Drive, then sync.

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
- `DATA_SOURCE` — `local` or `google_drive`
- `SHARED_DATA_DIR` — local cache path (required for both modes)
- `GOOGLE_DRIVE_FOLDER_ID` + `GOOGLE_SERVICE_ACCOUNT_JSON` — when using Google Drive
- `CORS_ORIGINS` — only needed if the frontend calls Render directly via `VITE_API_URL`

**Vercel**

- Optional: `VITE_API_URL=https://commodity-discrepancies.onrender.com` (host only is fine; `/api` is appended in the app). Set `CORS_ORIGINS` on Render to your Vercel origin.

Mount or set `SHARED_DATA_DIR` to a writable path on Render (e.g. `/tmp/commodity-data`). For Google Drive, no disk mount is required — files are downloaded via API.

## Troubleshooting

| Error | Fix |
|-------|-----|
| API 404 on Vercel | Add `frontend/vercel.json` or set `VITE_API_URL` to Render `/api` and redeploy |
| Data files missing | Check folder/Drive contents; click **Sync from Google Drive** or **Reload from folder** |
| Google Drive sync failed | Verify folder shared with service account; check `GOOGLE_DRIVE_FOLDER_ID` and JSON credentials |
| CORS blocked | Set `CORS_ORIGINS=https://your-app.vercel.app,http://localhost:5173` on Render |
| `command not found: python` | Use `python3` to create the venv; after `source .venv/bin/activate`, `python` works inside the venv |
| `unsupported operand type(s) for \|` | Caused by old **CrewAI on Python 3.9** — reinstall AI deps: `pip install -r requirements-ai.txt` (OpenAI SDK only, no CrewAI) |
| `No matching distribution found for crewai>=0.86` | Use `requirements-ai.txt` (OpenAI only) or `requirements-ai-py310.txt` if you want CrewAI on Python 3.10+ |
| `cd: no such file or directory: backend` | You are already inside `backend` — skip `cd backend` and run `bash start.sh` or uvicorn directly |
| `[Errno 48] Address already in use` | `pkill -f "uvicorn app.main:app"` or `lsof -i :8000` then `kill <PID>`; `start.sh` does this automatically |
| `zsh: command not found: #` | Paste commands **one line at a time**; don’t paste comment lines with `#` as commands |
| `command not found: python` | Use `python3` before venv exists; after `source .venv/bin/activate`, use `python` |

## Migrating to live SAP

Replace `DataStore.load_all()` with an SAP RFC/OData client that returns the same DataFrame schemas. The rule engine and agents remain unchanged.
