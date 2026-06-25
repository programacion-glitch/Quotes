"""
Google Drive Manager Module.

Handles integration with Google Drive API using a Service Account and optional
Domain-Wide Delegation impersonation.
"""

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from modules.config_manager import get_config

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


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
        # Modo de auth de Drive: 'user_oauth' (sube como el usuario dueño de la
        # carpeta — necesario para carpetas de My Drive, p.ej. quotes@) o
        # 'service_account' (solo sirve para Shared Drives). Default SA por
        # compatibilidad; se setea por env DRIVE_AUTH_MODE.
        self.drive_auth_mode = (
            os.getenv("DRIVE_AUTH_MODE")
            or self.config.get("drive.auth_mode", "service_account")
        ).strip().lower()
        self.user_token_path = self.config.get(
            "drive.user_token_path", "data/token.json"
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
        if self.drive_auth_mode == "user_oauth":
            return self._authenticate_user_oauth()

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

    def _authenticate_user_oauth(self):
        """Auth como USUARIO (OAuth) — sube como el dueño de la carpeta (con
        cuota). Reusa el token de quotes@ (data/token.json), que debe incluir
        el scope de Drive (re-consentir con scripts/gmail_oauth_bootstrap.py)."""
        token_path = Path(self.project_root()) / self.user_token_path
        if not token_path.exists():
            print(f"⚠️ Drive (user OAuth): token no encontrado en {token_path}. "
                  f"Corré scripts/gmail_oauth_bootstrap.py (con scope de Drive).")
            return None
        try:
            creds = UserCredentials.from_authorized_user_file(str(token_path))
        except Exception as e:
            print(f"✗ Drive (user OAuth): no se pudo cargar el token: {e}")
            return None

        if _DRIVE_SCOPE not in (creds.scopes or []):
            print(f"⚠️ Drive (user OAuth): el token NO tiene scope de Drive "
                  f"(scopes={creds.scopes}). Re-consentí con scope drive "
                  f"(scripts/gmail_oauth_bootstrap.py). No se subirá a Drive.")
            return None

        try:
            if not creds.valid:
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    token_path.write_text(creds.to_json(), encoding="utf-8")
                else:
                    print("✗ Drive (user OAuth): token inválido / sin refresh "
                          "token. Re-consentí.")
                    return None
            service = build("drive", "v3", credentials=creds,
                            cache_discovery=False)
            about = service.about().get(fields="user(emailAddress)").execute()
            email = about.get("user", {}).get("emailAddress", "user")
            self.auth_mode = "user_oauth"
            self.auth_identity = email
            print(f"  Drive: Authenticated as {email} (user OAuth)")
            return service
        except Exception as e:
            msg = str(e)
            if "has not been used" in msg or "is disabled" in msg:
                print(f"✗ Drive (user OAuth): Drive API deshabilitada en el "
                      f"proyecto de quotes@. Habilitala. Detalle: {e}")
            else:
                print(f"✗ Drive (user OAuth) auth falló: {e}")
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

    @staticmethod
    def _norm(s: str) -> str:
        """Normaliza para comparar nombres: solo alfanuméricos en mayúscula."""
        return "".join(ch for ch in (s or "").upper() if ch.isalnum())

    def _find_client_folder(self, business_name: str, usdot: str) -> Optional[str]:
        """Busca la carpeta del cliente en main_folder_id. Match por NÚMERO de
        DOT donde sea que aparezca (USDOT/US DOT/DOT); si no, por nombre de
        negocio normalizado. Devuelve el folder_id o None."""
        if not self.service or not self.main_folder_id:
            return None
        parent = self.main_folder_id
        fmime = "application/vnd.google-apps.folder"
        digits = re.sub(r"\D", "", str(usdot or ""))

        # 1) por número de DOT (robusto a 'USDOT 123' / 'US DOT 123' / 'DOT 123')
        if digits and len(digits) >= 5:
            try:
                res = self.service.files().list(
                    q=(f"'{parent}' in parents and mimeType='{fmime}' "
                       f"and name contains '{digits}' and trashed=false"),
                    spaces="drive", fields="files(id,name)",
                    supportsAllDrives=True, includeItemsFromAllDrives=True,
                    pageSize=50,
                ).execute()
                cands = [f for f in res.get("files", [])
                         if digits in re.sub(r"\D", "", f["name"])]
            except Exception as e:
                print(f"⚠️ Drive: error buscando carpeta por DOT {digits}: {e}")
                cands = []
            if cands:
                bn = self._norm(business_name)
                for f in cands:  # preferir el que además matchee el negocio
                    if bn and bn[:10] and bn[:10] in self._norm(f["name"]):
                        return f["id"]
                return cands[0]["id"]

        # 2) por nombre de negocio (primera palabra como ancla del query)
        bn = self._norm(business_name)
        words = (business_name or "").strip().split()
        if bn and words:
            token = words[0].replace("'", "\\'")
            try:
                res = self.service.files().list(
                    q=(f"'{parent}' in parents and mimeType='{fmime}' "
                       f"and name contains '{token}' and trashed=false"),
                    spaces="drive", fields="files(id,name)",
                    supportsAllDrives=True, includeItemsFromAllDrives=True,
                    pageSize=100,
                ).execute()
                for f in res.get("files", []):
                    if bn[:12] in self._norm(f["name"]):
                        return f["id"]
            except Exception as e:
                print(f"⚠️ Drive: error buscando carpeta por nombre: {e}")
        return None

    def _find_or_create_client_folder(self, business_name: str,
                                      usdot: str) -> Optional[str]:
        fid = self._find_client_folder(business_name, usdot)
        if fid:
            return fid
        digits = re.sub(r"\D", "", str(usdot or ""))
        bname = (business_name or "UNKNOWN").strip()
        name = f"{bname} USDOT {digits}" if digits else bname
        print(f"  Drive: carpeta de cliente no encontrada; creando '{name}'")
        return self._get_or_create_folder(name, parent_id=self.main_folder_id)

    def _find_or_create_quotes_subfolder(self,
                                         client_folder_id: str) -> Optional[str]:
        """Reusa una subcarpeta cuyo nombre contenga 'QUOTE' (p.ej. '2) QUotes');
        si no existe, crea '2) Quotes'."""
        fmime = "application/vnd.google-apps.folder"
        try:
            res = self.service.files().list(
                q=(f"'{client_folder_id}' in parents and mimeType='{fmime}' "
                   f"and trashed=false"),
                spaces="drive", fields="files(id,name)",
                supportsAllDrives=True, includeItemsFromAllDrives=True,
                pageSize=100,
            ).execute()
            for f in res.get("files", []):
                if "QUOTE" in (f["name"] or "").upper():
                    return f["id"]
        except Exception as e:
            print(f"⚠️ Drive: error listando subcarpetas de quotes: {e}")
        return self._get_or_create_folder("2) Quotes",
                                          parent_id=client_folder_id)

    def upload_quote_indication(self, business_name: str, usdot: str,
                                pdf_path: str, carrier: str = "Progressive",
                                when: Optional[datetime] = None) -> Optional[str]:
        """Sube el PDF de indicación a
        <carpeta cliente>/2) Quotes/'YYYYMMDD - Indications <carrier>.pdf'.
        Best-effort: devuelve file_id, 'exists' si ya estaba, o None. NUNCA
        levanta (un fallo de Drive no debe tumbar el flujo de cotización)."""
        if not self.service:
            print("⚠️ Drive no inicializado; no se sube la indicación.")
            return None
        if not self.main_folder_id:
            print("⚠️ DRIVE_MAIN_FOLDER_ID no seteado; no se sube la indicación.")
            return None
        p = Path(pdf_path) if pdf_path else None
        if not p or not p.exists():
            print(f"⚠️ Drive: el PDF de indicación no existe: {pdf_path}")
            return None
        try:
            client_id = self._find_or_create_client_folder(business_name, usdot)
            if not client_id:
                return None
            quotes_id = self._find_or_create_quotes_subfolder(client_id)
            if not quotes_id:
                return None
            date_str = (when or datetime.now()).strftime("%Y%m%d")
            label = {"PROGRESSIVE": "Progressive", "GEICO": "GEICO"}.get(
                (carrier or "").upper(), (carrier or "Quote").title())
            fname = f"{date_str} - Indications {label}.pdf"

            existing = self._list_existing_file_keys(quotes_id) or set()
            if self._filename_key(fname) in existing:
                print(f"  Drive: '{fname}' ya existe; no se re-sube.")
                return "exists"

            media = MediaFileUpload(str(p), mimetype="application/pdf",
                                    resumable=True)
            created = self.service.files().create(
                body={"name": fname, "parents": [quotes_id]},
                media_body=media, fields="id", supportsAllDrives=True,
            ).execute()
            print(f"  Drive: indicación subida → '{fname}' "
                  f"(id={created.get('id')})")
            return created.get("id")
        except Exception as e:
            print(f"✗ Drive: error subiendo la indicación: {e}")
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

        print(f"  Drive: buscando/creando carpeta de cliente para "
              f"'{business_name}' (USDOT {usdot})...")
        client_folder_id = self._find_or_create_client_folder(business_name, usdot)

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
