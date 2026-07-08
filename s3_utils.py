import os
import json
import logging

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

STATE_KEY = "state/processed_ids.json"

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)

def test_s3_connection():
    """
    Verify that the configured S3 bucket is accessible.
    """
    try:
        s3_client.head_bucket(Bucket=S3_BUCKET_NAME)
        print(f"Connected successfully to bucket: {S3_BUCKET_NAME}")
        return True

    except ClientError as e:
        logging.error(f"Failed to connect to bucket: {e}")
        return False
    
ALLOWED_FOLDERS = {
    "pdfs",
    "markdown",
    "metadata",
}

COURT_FOLDER = "SindhHighCourtJudgments"

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
}

def get_content_type(filename: str) -> str:
    """
    Return the correct ContentType for supported file types.
    """
    extension = os.path.splitext(filename)[1].lower()

    if extension not in CONTENT_TYPES:
        raise ValueError(f"Unsupported file type: {extension}")

    return CONTENT_TYPES[extension]

def upload_file(
    local_file_path: str,
    folder: str,
    overwrite: bool = False,
) -> tuple[str, bool]:
    """
    Upload a local file to S3.

    Args:
        local_file_path: Path to the local file.
        folder: One of 'pdfs', 'markdown', or 'metadata'.
        overwrite: If True, upload even if the object already exists.

    Returns:
        (s3_key, uploaded)

        uploaded:
            True  -> file uploaded
            False -> upload skipped because it already exists
    """

    if folder not in ALLOWED_FOLDERS:
        raise ValueError(
            f"Invalid folder '{folder}'. "
            f"Expected one of: {sorted(ALLOWED_FOLDERS)}"
        )

    filename = os.path.basename(local_file_path)

    s3_key = build_s3_key(folder, filename)

    if not overwrite and object_exists(s3_key):
        logging.info(f"Skipping upload (already exists): {s3_key}")
        return s3_key, False

    content_type = get_content_type(filename)

    try:
        s3_client.upload_file(
            Filename=local_file_path,
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            ExtraArgs={
                "ContentType": content_type,
            },
        )

        logging.info(f"Uploaded: {s3_key}")

        return s3_key, True

    except ClientError as e:
        logging.error(f"Upload failed: {e}")
        raise

def build_s3_key(folder: str, filename: str) -> str:
    """
    Build the S3 object key according to the required hierarchy.

    Example:
    pdfs/SindhHighCourtJudgments/
    Sindh+High+Court+-+2026SHC153.pdf
    """

    s3_filename = filename.replace(" ", "+")

    return f"{folder}/{COURT_FOLDER}/{s3_filename}"

def object_exists(s3_key: str) -> bool:
    """
    Check whether an object already exists in the S3 bucket.
    Returns True if it exists, False otherwise.
    """
    try:
        s3_client.head_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
        )
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]

        if error_code in ("404", "NoSuchKey"):
            return False

        raise


def download_state_file() -> dict:
    """
    Returns:
    {
        identifier: {
            "fileName": "...",
            "citation": "..."
        }
    }

    Returns {} if the state file does not exist.
    """

    try:
        response = s3_client.get_object(
            Bucket=S3_BUCKET_NAME,
            Key=STATE_KEY,
        )

        return json.loads(
            response["Body"].read().decode("utf-8")
        )

    except ClientError as e:

        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return {}

        raise

def upload_state_file(processed: dict) -> None:
    """
    Upload the processed state file to S3.

    processed:
    {
        identifier: {
            "fileName": "...",
            "citation": "..."
        }
    }
    """

    try:
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=STATE_KEY,
            Body=json.dumps(
                processed,
                indent=2,
                ensure_ascii=False,
            ).encode("utf-8"),
            ContentType="application/json",
        )

        logging.info("State file uploaded successfully.")

    except ClientError as e:
        logging.error(f"Failed to upload state file: {e}")
        raise

