from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, router
from app.config import settings
from app.services.app_logger import configure_logging, log_info, log_warning
from app.services.data_loader import data_store, sync_data_source

app = FastAPI(
    title="Commodity Discrepancy Analysis API",
    description="VBAP vs CMM_VLOGP discrepancy detection with AI-powered root-cause analysis",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

# Alias for Render health checks or VITE_API_URL without /api prefix
app.get("/health")(health)


@app.on_event("startup")
def startup():
    configure_logging()
    settings.shared_data_dir.mkdir(parents=True, exist_ok=True)
    log_info("system", "Commodity Discrepancy Analysis API starting")
    if settings.uses_google_drive:
        try:
            sync_result = sync_data_source()
            log_info("system", f"Google Drive sync: {sync_result.get('message', 'done')}")
        except Exception as exc:
            log_warning("system", f"Google Drive sync on startup failed: {exc}")
    data_store.load_all()
    log_info(
        "system",
        f"Initial data load complete — tables: {', '.join(data_store.loaded_tables()) or 'none'}",
    )


@app.get("/")
def root():
    return {
        "service": "Commodity Discrepancy Analysis",
        "docs": "/docs",
        "health": "/api/health",
    }
