"""Download SAP CSV/Excel exports from a Google Drive folder into the local cache."""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from app.config import settings
from app.services.data_loader import (
    SUPPORTED_DATA_EXTENSIONS,
    TABLE_FILES,
    resolve_upload_filename,
)

DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)
CSV_MIME_TYPES = {
    "text/csv",
    "application/csv",
    "text/plain",
}
EXCEL_MIME_TYPES = {
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
DATA_MIME_TYPES = CSV_MIME_TYPES | EXCEL_MIME_TYPES


@dataclass
class GoogleDriveSyncResult:
    synced: bool = False
    skipped: bool = False
    downloaded: List[str] = field(default_factory=list)
    drive_files_seen: int = 0
    message: str = ""


def is_google_drive_configured() -> bool:
    if settings.data_source.lower() != "google_drive":
        return False
    if not settings.google_drive_folder_id.strip():
        return False
    return _credentials_source() is not None


def _credentials_source() -> Optional[str]:
    if (settings.google_service_account_json or "").strip():
        return "json"
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if creds_path and Path(creds_path).exists():
        return "file"
    return None


def _build_drive_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google Drive dependencies not installed. "
            "Run: pip install google-api-python-client google-auth"
        ) from exc

    source = _credentials_source()
    if source == "json":
        info = json.loads(settings.google_service_account_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=DRIVE_SCOPES
        )
    elif source == "file":
        creds = service_account.Credentials.from_service_account_file(
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
            scopes=DRIVE_SCOPES,
        )
    else:
        raise RuntimeError(
            "Google Drive not configured. Set GOOGLE_DRIVE_FOLDER_ID and either "
            "GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS."
        )

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _is_data_drive_file(name: str, mime_type: str) -> bool:
    lower = name.lower()
    if any(lower.endswith(ext) for ext in SUPPORTED_DATA_EXTENSIONS):
        return True
    return mime_type in DATA_MIME_TYPES


def _pick_best_drive_files(files: List[dict]) -> Dict[str, dict]:
    """Map canonical table filename -> best matching Drive file (newest wins)."""
    chosen: Dict[str, dict] = {}
    for item in files:
        name = item.get("name") or ""
        if not _is_data_drive_file(name, item.get("mimeType") or ""):
            continue
        canonical = resolve_upload_filename(name)
        if not canonical:
            continue
        current = chosen.get(canonical)
        if not current or (item.get("modifiedTime") or "") >= (
            current.get("modifiedTime") or ""
        ):
            chosen[canonical] = item
    return chosen


def sync_from_google_drive() -> GoogleDriveSyncResult:
    """Download required SAP exports from Google Drive into shared_data_dir cache."""
    if settings.data_source.lower() != "google_drive":
        return GoogleDriveSyncResult(
            skipped=True,
            message="DATA_SOURCE is not google_drive",
        )

    folder_id = settings.google_drive_folder_id.strip()
    if not folder_id:
        raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID is required when DATA_SOURCE=google_drive")

    cache_dir = settings.shared_data_dir
    cache_dir.mkdir(parents=True, exist_ok=True)

    service = _build_drive_service()
    query = f"'{folder_id}' in parents and trashed = false"
    response = (
        service.files()
        .list(
            q=query,
            fields="files(id,name,mimeType,modifiedTime)",
            pageSize=200,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    drive_files = response.get("files") or []
    picked = _pick_best_drive_files(drive_files)

    from googleapiclient.http import MediaIoBaseDownload

    downloaded: List[str] = []
    for canonical in TABLE_FILES.values():
        item = picked.get(canonical)
        if not item:
            continue
        name = item["name"]
        dest = cache_dir / name
        request = service.files().get_media(fileId=item["id"])
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        dest.write_bytes(buffer.getvalue())
        downloaded.append(name)

    missing = sorted(set(TABLE_FILES.values()) - set(picked.keys()))
    message = f"Synced {len(downloaded)} file(s) from Google Drive."
    if missing:
        message += f" Missing in folder: {', '.join(missing)}."

    return GoogleDriveSyncResult(
        synced=True,
        downloaded=downloaded,
        drive_files_seen=len(drive_files),
        message=message,
    )
