"""
Google Drive Manager Module.

Handles integration with Google Drive API using a Service Account and optional
Domain-Wide Delegation impersonation.
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from modules.config_manager import get_config


def _env_flag(var_name: str, default: bool = False) -> bool:
    """Parse boolean environment variables safely."""
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class DriveManager:
    """Manages Google Drive operations (folder creation, file upload)."""

    SCOPES = ["https://www.googleapis.com/auth/drive"]

    def __init__(self):
        """Initialize DriveManager, load credentials, and build the service."""
        self.config = get_config()
        self.credentials_path = self.config.get(
            "drive.credentials_path",
            "config/drivequotes-10596e569f01.json",
        )
        self.main_folder_id = os.getenv("DRIVE_MAIN_FOLDER_ID")

        self.impersonate_user = (
            os.getenv("DRIVE_IMPERSONATE_USER")
            or os.getenv("EMAIL_USERNAME")
            or os.getenv("EMAIL_FROM")
        )
        self.allow_service_account_fallback = _env_flag(
            "DRIVE_ALLOW_SERVICE_ACCOUNT_FALLBACK",
            True,
        )

        self.auth_mode = "unknown"
        self.auth_identity = None

        self.service = self._authenticate()

    def project_root(self) -> Path:
        """Return project root path."""
        return Path(__file__).parent.parent

    @staticmethod
    def _escape_drive_query_value(value: str) -> str:
        """Escape values used in Drive query strings."""
        return value.replace("\\", "\\\\").replace("'", "\\'")

    @staticmethod
    def _filename_key(filename: str) -> str:
        """Normalize filename for duplicate detection."""
        return filename.strip().casefold()

    def _authenticate(self):
        """Authenticate with Google Drive API."""
        creds_path = Path(self.project_root()) / self.credentials_path
        if not creds_path.exists():
            print(f"⚠️ Drive credentials not found at: {creds_path}")
            return None

        try:
            base_creds = service_account.Credentials.from_service_account_file(
                str(creds_path),
                scopes=self.SCOPES,
            )
        except Exception as e:
            print(f"✗ Failed to load Drive credentials: {e}")
            return None

        if self.impersonate_user:
            try:
                delegated_creds = base_creds.with_subject(self.impersonate_user)
                service = build("drive", "v3", credentials=delegated_creds)
                about = service.about().get(fields="user(emailAddress)").execute()
                delegated_email = about.get("user", {}).get("emailAddress", self.impersonate_user)
                self.auth_mode = "delegated_user"
                self.auth_identity = delegated_email
                print(f"  Drive: Authenticated as {delegated_email} (delegated user)")
                return service
            except Exception as delegated_error:
                print(
                    "  Drive: Delegated auth failed "
                    f"for '{self.impersonate_user}': {delegated_error}"
                )
                if not self.allow_service_account_fallback:
                    print("  Drive: Service Account fallback disabled. Drive upload skipped.")
                    return None
                print("  Drive: Falling back to Service Account authentication.")
        else:
            print(
                "  Drive: No impersonation user configured. "
                "Trying Service Account authentication."
            )

        try:
            service = build("drive", "v3", credentials=base_creds)
            about = service.about().get(fields="user(emailAddress)").execute()
            service_account_email = about.get("user", {}).get("emailAddress", "service-account")
            self.auth_mode = "service_account"
            self.auth_identity = service_account_email
            print(f"  Drive: Authenticated as {service_account_email} (service account)")
            return service
        except Exception as e:
            print(f"✗ Failed to authenticate with Google Drive: {e}")
            return None

    def _is_folder_in_shared_drive(self, folder_id: str) -> Optional[bool]:
        """
        Check if a folder belongs to a Shared Drive.

        Returns:
            True: Folder is in Shared Drive
            False: Folder is in My Drive
            None: Could not determine
        """
        if not self.service or not folder_id:
            return None

        try:
            metadata = self.service.files().get(
                fileId=folder_id,
                fields="id,name,driveId",
                supportsAllDrives=True,
            ).execute()
            return bool(metadata.get("driveId"))
        except Exception as e:
            print(f"⚠️ Drive: Could not inspect main folder '{folder_id}': {e}")
            return None

    def _get_or_create_folder(self, folder_name: str, parent_id: Optional[str] = None) -> Optional[str]:
        """
        Find a folder by name inside a parent folder, or create it if missing.
        """
        if not self.service:
            return None

        escaped_name = self._escape_drive_query_value(folder_name)
        query = (
            "mimeType='application/vnd.google-apps.folder' "
            f"and name='{escaped_name}' and trashed=false"
        )
        if parent_id:
            query += f" and '{parent_id}' in parents"

        try:
            results = self.service.files().list(
                q=query,
                spaces="drive",
                fields="files(id,name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            items = results.get("files", [])

            if items:
                return items[0]["id"]

            if parent_id:
                file_metadata: Dict[str, object] = {
                    "name": folder_name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_id],
                }
            else:
                file_metadata = {
                    "name": folder_name,
                    "mimeType": "application/vnd.google-apps.folder",
                }

            folder = self.service.files().create(
                body=file_metadata,
                fields="id",
                supportsAllDrives=True,
            ).execute()
            return folder.get("id")

        except Exception as e:
            print(f"✗ Failed to get/create folder '{folder_name}': {e}")
            return None

    def _list_existing_file_keys(self, folder_id: str) -> Optional[Set[str]]:
        """
        List existing filenames in a folder as normalized keys.

        Returns:
            Set of normalized filenames or None if listing fails.
        """
        if not self.service:
            return None

        query = f"'{folder_id}' in parents and trashed=false"
        page_token = None
        existing_keys: Set[str] = set()

        try:
            while True:
                response = self.service.files().list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken,files(name)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    pageToken=page_token,
                ).execute()

                for item in response.get("files", []):
                    name = item.get("name")
                    if name:
                        existing_keys.add(self._filename_key(name))

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            return existing_keys
        except Exception as e:
            print(f"⚠️ Drive: Could not list existing files in folder '{folder_id}': {e}")
            return None

    def upload_files_for_client(self, business_name: str, usdot: str, attachments: List[Dict]) -> bool:
        """
        Upload all related files for a specific client into their own folder.
        """
        if not self.service:
            print("⚠️ Drive API not initialized. Cannot upload.")
            return False

        if not self.main_folder_id:
            print("⚠️ DRIVE_MAIN_FOLDER_ID not set in .env. Cannot upload.")
            return False

        if self.auth_mode == "service_account":
            is_shared_drive = self._is_folder_in_shared_drive(self.main_folder_id)
            if is_shared_drive is False:
                print("✗ Drive configuration issue detected:")
                print("  - Auth mode: Service Account")
                print("  - Main folder: My Drive (not Shared Drive)")
                print("  - Result: Upload fails with 'storageQuotaExceeded'")
                print("  Fix options:")
                print("    1) Configure DRIVE_IMPERSONATE_USER with a Workspace user")
                print("    2) Point DRIVE_MAIN_FOLDER_ID to a Shared Drive folder")
                return False
            if is_shared_drive is None:
                print(
                    "⚠️ Drive: Could not verify whether DRIVE_MAIN_FOLDER_ID is in Shared Drive. "
                    "Uploads may fail if it belongs to My Drive."
                )

        usdot_str = str(usdot).strip() if usdot else "UNKNOWN"
        bname_str = str(business_name).strip() if business_name else "UNKNOWN"
        client_folder_name = f"{bname_str} USDOT {usdot_str}"

        print(f"  Drive: Creating/finding folder '{client_folder_name}'...")
        client_folder_id = self._get_or_create_folder(client_folder_name, parent_id=self.main_folder_id)

        if not client_folder_id:
            return False

        existing_file_keys = self._list_existing_file_keys(client_folder_id)
        if existing_file_keys is None:
            existing_file_keys = set()

        success = True
        for att in attachments:
            filename = att.get("filename")
            data = att.get("data")
            content_type = att.get("content_type", "application/octet-stream")

            if not filename or not data:
                continue

            filename_key = self._filename_key(filename)
            if filename_key in existing_file_keys:
                print(f"  Drive: Skipping '{filename}' (already exists)")
                continue

            tmp_path = None
            try:
                suffix = Path(filename).suffix or ".pdf"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                    tmp_file.write(data)
                    tmp_path = tmp_file.name

                print(f"  Drive: Uploading '{filename}'...")

                file_metadata = {
                    "name": filename,
                    "parents": [client_folder_id],
                }
                media = MediaFileUpload(tmp_path, mimetype=content_type, resumable=True)

                created_file = self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields="id",
                    supportsAllDrives=True,
                ).execute()

                file_id = created_file.get("id")
                print(f"    ✓ Uploaded '{filename}'")
                if file_id:
                    existing_file_keys.add(filename_key)

            except HttpError as e:
                error_text = str(e)
                if "storageQuotaExceeded" in error_text:
                    print(
                        f"    ✗ Error uploading '{filename}': Storage quota exceeded for current auth context."
                    )
                    if self.auth_mode == "service_account":
                        print(
                            "      Use DRIVE_IMPERSONATE_USER or move DRIVE_MAIN_FOLDER_ID to a Shared Drive."
                        )
                else:
                    print(f"    ✗ Error uploading '{filename}': {e}")
                success = False
            except Exception as e:
                print(f"    ✗ Error uploading '{filename}': {e}")
                success = False
            finally:
                if tmp_path and Path(tmp_path).exists():
                    try:
                        Path(tmp_path).unlink()
                    except OSError:
                        pass

        return success
