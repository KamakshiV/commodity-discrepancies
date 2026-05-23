from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.services.app_logger import configure_logging, log_info
from app.services.data_loader import data_store

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


@app.on_event("startup")
def startup():
    configure_logging()
    log_info("system", "Commodity Discrepancy Analysis API starting")
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
