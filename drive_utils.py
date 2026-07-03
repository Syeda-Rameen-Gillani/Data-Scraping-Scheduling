import os
import os.path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")


def authenticate():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)

def upload_pdf_to_drive(pdf_path):
    service = authenticate()

    filename = os.path.basename(pdf_path)

    # Check whether this file already exists in the target folder
    query = (
        f"name='{filename}' and "
        f"'{FOLDER_ID}' in parents and "
        f"trashed=false"
    )

    results = (
        service.files()
        .list(
            q=query,
            fields="files(id, name)"
        )
        .execute()
    )

    files = results.get("files", [])

    # If it already exists, return its URL instead of uploading again
    if files:
        file_id = files[0]["id"]
        return f"https://drive.google.com/file/d/{file_id}/view"

    # Upload if it doesn't exist
    file_metadata = {
        "name": filename,
        "parents": [FOLDER_ID],
    }

    media = MediaFileUpload(
        pdf_path,
        mimetype="application/pdf",
        resumable=True,
    )

    file = (
        service.files()
        .create(
            body=file_metadata,
            media_body=media,
            fields="id",
        )
        .execute()
    )

    file_id = file["id"]

    # Make it publicly viewable
    service.permissions().create(
        fileId=file_id,
        body={
            "type": "anyone",
            "role": "reader",
        },
    ).execute()

    return f"https://drive.google.com/file/d/{file_id}/view"
