"""
Drive Sheet Sync.

Downloads a Google Drive file to a local xlsx path, with cache + fallback.

This lets the existing readers (RuleEngine, MGAReader, COMMTDNMapper,
MGAEmailReader) keep working against a local xlsx while still reflecting
edits made in Drive by business users.

Auth: OAuth user credentials saved at config/oauth_user_token.json
(produced by tools/read_sheet_as_user.py on first run).

Behavior:
  - If local file is fresher than `max_age_minutes`: skip download.
  - If Drive download succeeds: overwrite local file.
  - If Drive download fails AND local file exists: log warning, keep local
    (resilience - workflow still runs with last known version).
  - If Drive download fails AND no local file: raise.
"""

from __future__ import annotations

import io
import os
import time
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

# Files
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOKEN_PATH = PROJECT_ROOT / "config" / "oauth_user_token.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# MIME types
GSHEETS_MIME = "application/vnd.google-apps.spreadsheet"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class DriveSheetSyncError(RuntimeError):
    """Raised when Drive sync fails and no local fallback is available."""


def _load_credentials(token_path: Path) -> Credentials:
    if not token_path.exists():
        raise DriveSheetSyncError(
            f"OAuth token not found at {token_path}. "
            "Run `python tools/read_sheet_as_user.py` once to create it."
        )
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _local_is_fresh(local_path: Path, max_age_minutes: int) -> bool:
    if not local_path.exists():
        return False
    age_minutes = (time.time() - local_path.stat().st_mtime) / 60.0
    return age_minutes < max_age_minutes


def sync_to_local(
    file_id: str,
    local_path: Path | str,
    max_age_minutes: int = 5,
    token_path: Path | str = DEFAULT_TOKEN_PATH,
    force: bool = False,
) -> Path:
    """Download `file_id` from Drive to `local_path` if needed.

    Args:
        file_id: Google Drive file ID.
        local_path: where to save the xlsx.
        max_age_minutes: skip download if local file is fresher than this.
        token_path: path to OAuth user token.
        force: ignore cache, always download.

    Returns:
        The local Path written (or already present and fresh).

    Raises:
        DriveSheetSyncError: if download fails and no local file exists.
    """
    local_path = Path(local_path)
    token_path = Path(token_path)

    if not force and _local_is_fresh(local_path, max_age_minutes):
        return local_path

    try:
        creds = _load_credentials(token_path)
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        meta = drive.files().get(
            fileId=file_id, fields="id,name,mimeType,modifiedTime"
        ).execute()

        mime = meta.get("mimeType")
        if mime == GSHEETS_MIME:
            request = drive.files().export_media(fileId=file_id, mimeType=XLSX_MIME)
        elif mime in (XLSX_MIME, "application/vnd.ms-excel"):
            request = drive.files().get_media(fileId=file_id)
        else:
            raise DriveSheetSyncError(f"Unsupported mimeType: {mime}")

        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(buf.getvalue())
        print(
            f"  Drive: Synced '{meta['name']}' "
            f"(modified={meta.get('modifiedTime')}) -> {local_path.name}"
        )
        return local_path

    except (HttpError, DriveSheetSyncError, Exception) as e:
        if local_path.exists():
            age_minutes = (time.time() - local_path.stat().st_mtime) / 60.0
            print(
                f"  Drive sync FAILED ({e!s:.150}). "
                f"Using existing local file (age={age_minutes:.1f} min)."
            )
            return local_path
        # No local file available - hard fail
        raise DriveSheetSyncError(
            f"Drive download failed and no local fallback exists at {local_path}: {e}"
        ) from e


def sync_from_env(default_local_path: Path | str) -> Path:
    """Convenience: sync using env vars.

    Env vars:
        REGLAS_DRIVE_FILE_ID    - Drive file ID of the checklist xlsx
        REGLAS_SYNC_ENABLED     - "true" (default) to enable sync
        REGLAS_CACHE_MINUTES    - max cache age (default 5)

    Returns:
        Path to the local xlsx (synced or fallback).
    """
    local_path = Path(default_local_path)
    if os.getenv("REGLAS_SYNC_ENABLED", "true").lower() not in ("1", "true", "yes"):
        return local_path

    file_id = os.getenv("REGLAS_DRIVE_FILE_ID")
    if not file_id:
        # No file_id configured -> stay with local
        return local_path

    cache_min = int(os.getenv("REGLAS_CACHE_MINUTES", "5"))
    return sync_to_local(file_id, local_path, max_age_minutes=cache_min)
