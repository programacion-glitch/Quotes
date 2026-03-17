"""
Google Drive Manager Module

Handles integration with Google Drive API using a Service Account.
Responsible for creating folders and uploading files to specific locations.
"""

import os
from pathlib import Path
from typing import List, Dict, Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from modules.config_manager import get_config


class DriveManager:
    """Manages Google Drive operations (folder creation, file upload)."""
    
    # Scopes required for Google Drive API
    SCOPES = ['https://www.googleapis.com/auth/drive']
    
    def __init__(self):
        """Initialize DriveManager, load credentials, and build the service."""
        self.config = get_config()
        self.credentials_path = self.config.get("drive.credentials_path", "config/drivequotes-10596e569f01.json")
        self.main_folder_id = os.getenv("DRIVE_MAIN_FOLDER_ID")
        
        self.service = self._authenticate()
        
    def _authenticate(self):
        """Authenticate using the service account credentials."""
        creds_path = Path(self.project_root()) / self.credentials_path
        if not creds_path.exists():
            print(f"⚠️ Drive credentials not found at: {creds_path}")
            return None
            
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(creds_path), scopes=self.SCOPES)
            service = build('drive', 'v3', credentials=creds)
            return service
        except Exception as e:
            print(f"✗ Failed to authenticate with Google Drive: {e}")
            return None
            
    def project_root(self) -> Path:
        return Path(__file__).parent.parent
            
    def _get_or_create_folder(self, folder_name: str, parent_id: Optional[str] = None) -> Optional[str]:
        """
        Finds a folder by name inside a parent folder. 
        If it doesn't exist, it creates it.
        
        Args:
            folder_name: Name of the folder to find/create
            parent_id: Optional ID of the parent folder
            
        Returns:
            The folder ID, or None if failed
        """
        if not self.service:
            return None
            
        # 1. Search for existing folder
        query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
            
            try:
                results = self.service.files().list(
                    q=query, spaces='drive', fields='files(id, name)',
                    supportsAllDrives=True, includeItemsFromAllDrives=True
                ).execute()
                items = results.get('files', [])
                
                if items:
                    # Return the ID of the first match
                    return items[0]['id']
                    
                # 2. If not found, create it
                file_metadata = {
                    'name': folder_name,
                    'mimeType': 'application/vnd.google-apps.folder'
                }
                if parent_id:
                    file_metadata['parents'] = [parent_id]
                    
                folder = self.service.files().create(
                    body=file_metadata, fields='id',
                    supportsAllDrives=True
                ).execute()
                return folder.get('id')
                
            except Exception as e:
                print(f"✗ Failed to get/create folder '{folder_name}': {e}")
                return None
                
        def upload_files_for_client(self, business_name: str, usdot: str, attachments: List[Dict]) -> bool:
            """
            Uploads all related files for a specific client into their own folder.
            
            Args:
                business_name: Name of the business (from Blue Quote)
                usdot: USDOT number (from Blue Quote)
                attachments: List of attachment dictionaries [{'filename': str, 'data': bytes}]
                
            Returns:
                True if upload was completely successful, False otherwise.
            """
            if not self.service:
                print("⚠️ Drive API not initialized. Cannot upload.")
                return False
                
            if not self.main_folder_id:
                print("⚠️ DRIVE_MAIN_FOLDER_ID not set in .env. Cannot upload.")
                return False
                
            # Format the client folder name
            usdot_str = str(usdot).strip() if usdot else "UNKNOWN"
            bname_str = str(business_name).strip() if business_name else "UNKNOWN"
            client_folder_name = f"{bname_str} USDOT {usdot_str}"
            
            print(f"  Drive: Creating/finding folder '{client_folder_name}'...")
            client_folder_id = self._get_or_create_folder(client_folder_name, parent_id=self.main_folder_id)
            
            if not client_folder_id:
                return False
                
            # Subir cada archivo
            success = True
            for att in attachments:
                filename = att.get('filename')
                data = att.get('data')
                
                if not filename or not data:
                    continue
                    
                try:
                    # 1. Escribir los bytes a un archivo temporal para que googleapiclient pueda leerlo
                    import tempfile
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                        tmp_file.write(data)
                        tmp_path = tmp_file.name
                        
                    print(f"  Drive: Uploading '{filename}'...")
                    
                    # 2. Subir a Drive con soporte para Shared Drives
                    file_metadata = {
                        'name': filename,
                        'parents': [client_folder_id]
                    }
                    media = MediaFileUpload(tmp_path, resumable=True)
                    
                    self.service.files().create(
                        body=file_metadata,
                        media_body=media,
                        fields='id',
                        supportsAllDrives=True
                    ).execute()
                    
                    print(f"    ✓ Uploaded '{filename}'")
                
                # 3. Borrar el archivo temporal
                Path(tmp_path).unlink()
                
            except Exception as e:
                print(f"    ✗ Error uploading '{filename}': {e}")
                success = False
                
        return success
