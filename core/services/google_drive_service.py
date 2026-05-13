import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import webbrowser
from core.config import ROOT_FOLDER

SCOPES = ["https://www.googleapis.com/auth/drive"]



class GoogleDriveService:

    _memory_creds = None

    def __init__(self):
        if getattr(sys, 'frozen', False):
            bundle_dir = sys._MEIPASS
        else:
            bundle_dir = os.path.dirname(os.path.abspath(__file__))
            bundle_dir = os.path.join(bundle_dir, "..", "..")
        self.secret_path = os.path.normpath(os.path.join(bundle_dir, "auth", "client_secret.json"))


    def authenticate(self):
        creds = GoogleDriveService._memory_creds

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            GoogleDriveService._memory_creds = creds
            return creds

        flow = InstalledAppFlow.from_client_secrets_file(self.secret_path, SCOPES)

        browser_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]

        browser_executable = None
        for path in browser_paths:
            if os.path.exists(path):
                browser_executable = path
                break

        if browser_executable:
            webbrowser.register('modern_browser', None, webbrowser.BackgroundBrowser(browser_executable))
            GoogleDriveService._memory_creds = flow.run_local_server(port=0, browser='modern_browser')
        else:
            GoogleDriveService._memory_creds = flow.run_local_server(port=0)
        return GoogleDriveService._memory_creds

    def get_drive_client(self):
        creds = self.authenticate()
        return build("drive", "v3", credentials=creds)

    def get_or_create_folder(self, folder_name, root_folder_id):
        service = self.get_drive_client()

        query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false and '{root_folder_id}' in parents"

        response = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)',
            includeItemsFromAllDrives=True,
            supportsAllDrives=True
        ).execute()

        files = response.get('files', [])

        if files:
            return files[0].get('id')

        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [root_folder_id]
        }

        folder = service.files().create(
            body=file_metadata,
            fields="id",
            supportsAllDrives=True
        ).execute()

        return folder.get("id")

    def upload_file(self, file_path, custom_file_name, folder_id=None):
        service = self.get_drive_client()

        file_metadata = {
            "name": custom_file_name
        }

        if folder_id:
            file_metadata["parents"] = [folder_id]

        media = MediaFileUpload(file_path, resumable=True)

        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True
        ).execute()

        return file.get("id")

    def upload_backup_custom(self, file_path, folder_level_1, folder_level_2, custom_file_name, client_email=None):
        id_folder_1 = self.get_or_create_folder(folder_level_1, ROOT_FOLDER)
        id_folder_2 = self.get_or_create_folder(folder_level_2, id_folder_1)

        folder_link = None
        if client_email:
            try:
                self.share_file_with_email(id_folder_2, client_email)
            except Exception as e:
                if 'shareInNotPermitted' in str(e):
                    pass  # administrador bloqueou compartilhamento externo, continua sem compartilhar
                else:
                    raise
            service = self.get_drive_client()
            folder_info = service.files().get(fileId=id_folder_2, fields="webViewLink",
                                              supportsAllDrives=True).execute()
            folder_link = folder_info.get("webViewLink")

        file_id = self.upload_file(file_path, custom_file_name, id_folder_2)
        return file_id, folder_link

    def share_file_with_email(self, file_id, client_email):
        service = self.get_drive_client()

        user_permission = {
            'type': 'user',
            'role': 'writer',
            'emailAddress': client_email
        }

        try:
            service.permissions().create(
                fileId=file_id,
                body=user_permission,
                fields='id',
                sendNotificationEmail=False,
                supportsAllDrives=True
            ).execute()
        except Exception as e:
            if 'invalidSharingRequest' in str(e):
                service.permissions().create(
                    fileId=file_id,
                    body=user_permission,
                    fields='id',
                    sendNotificationEmail=True,
                    supportsAllDrives=True
                ).execute()
            else:
                raise

    def get_authenticated_user_email(self):
        service = self.get_drive_client()
        about_info = service.about().get(fields="user").execute()
        return about_info['user']['emailAddress']