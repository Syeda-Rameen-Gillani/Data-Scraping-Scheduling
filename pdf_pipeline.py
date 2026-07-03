import os
import requests

PDF_DIR = "data/pdfs"
os.makedirs(PDF_DIR, exist_ok=True)


def download_pdf(pdf_url: str, filename: str):
    """
    Downloads PDF from SHC website and saves locally
    """

    try:
        response = requests.get(pdf_url, timeout=30)
        response.raise_for_status()

        file_path = os.path.join(PDF_DIR, filename)

        with open(file_path, "wb") as f:
            f.write(response.content)

        return file_path

    except Exception as e:
        print(f"Failed to download {pdf_url}: {e}")
        return None