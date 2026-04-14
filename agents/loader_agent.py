"""
loader_agent.py — Agent 1
=========================
Loads PDF files from:

  - local folder  (source="local")
  - Google Drive  (source="gdrive")
  - Gmail         (source="gmail")

Returns a list of local file paths ready for Agent 2 (extractor_agent).

Configuration (via .env):
  GDRIVE_FOLDER_ID        GDrive folder ID to scan (required for gdrive)
  GOOGLE_CREDENTIALS_FILE Path to OAuth2 credentials JSON (default: credentials.json)
  GMAIL_SEARCH_QUERY      Gmail search string (default: subject:(invoice OR freight) has:attachment)
  GMAIL_MAX_RESULTS       Max emails to scan   (default: 30)
  GDRIVE_RECURSIVE        Set to "true" to scan sub-folders (default: true)
"""

import base64
import io
import logging
from pathlib import Path

from core.config import (
    SAMPLE_PDF_DIR,
    GDRIVE_FOLDER_ID,
    GOOGLE_CREDENTIALS_FILE,
    GMAIL_SEARCH_QUERY,
    GMAIL_MAX_RESULTS,
    GDRIVE_RECURSIVE,
)
from core.db import log_agent
from core.google_auth import get_drive_service, get_gmail_service

logger = logging.getLogger(__name__)
AGENT_NAME = "loader_agent"

#  MIME type for Google Docs (exportable as PDF) 
_GOOGLE_DOCS_MIME = "application/vnd.google-apps.document"
_GOOGLE_SHEETS_MIME = "application/vnd.google-apps.spreadsheet"
_GOOGLE_SLIDES_MIME = "application/vnd.google-apps.presentation"
_NATIVE_PDF_MIME = "application/pdf"


#  PUBLIC ENTRY POINT

def run(source: str = "local") -> list[str]:
    """
    Load PDF paths from the chosen source.

    Args:
        source: "local" | "gdrive" | "gmail"

    Returns:
        List of absolute/relative paths to PDF files on disk.
    """
    logger.info(" [Agent 1] Loading PDFs — source='%s'", source)

    if source == "local":
        paths = _load_local()
    elif source == "gdrive":
        paths = _load_gdrive()
    elif source == "gmail":
        paths = _load_gmail()
    else:
        logger.error("Unknown source '%s'. Valid options: local / gdrive / gmail", source)
        paths = []

    if paths:
        log_agent(AGENT_NAME, "success", f"Loaded {len(paths)} PDF(s) from {source}")
        logger.info(" [Agent 1] Found %d PDF(s)", len(paths))
        for p in paths:
            logger.info("   • %s", p)
    else:
        log_agent(AGENT_NAME, "failure", f"No PDFs found in source={source}")
        logger.warning(" [Agent 1] No PDFs found.")

    return paths


#  SOURCE: LOCAL FOLDER 

def _load_local() -> list[str]:
    """Recursively scan SAMPLE_PDF_DIR and return all .pdf file paths."""
    folder = Path(SAMPLE_PDF_DIR)
    if not folder.exists():
        logger.warning("Local PDF folder '%s' not found — creating it.", folder)
        folder.mkdir(parents=True, exist_ok=True)
        return []

    paths = sorted(str(p) for p in folder.rglob("*.pdf"))
    logger.info("Found %d local PDF(s) in '%s'.", len(paths), folder)
    return paths


#  SOURCE: GOOGLE DRIVE 

def _load_gdrive() -> list[str]:
    """
    Download all PDFs (and optionally Google Docs exported as PDF) from a
    Google Drive folder.

    Behavior:
    - Authenticates via OAuth2 (browser popup on first run; token cached in
      token_drive.json for subsequent runs).
    - Skips files already downloaded (based on filename).
    - If GDRIVE_RECURSIVE=true, also scans sub-folders recursively.
    - Google Docs / Sheets / Slides are exported to PDF on-the-fly.
    """
    if not GDRIVE_FOLDER_ID:
        logger.error(
            "GDRIVE_FOLDER_ID is not set in .env — cannot load from Google Drive.\n"
            "  1. Open your GDrive folder in a browser.\n"
            "  2. Copy the folder ID from the URL (the part after /folders/).\n"
            "  3. Set GDRIVE_FOLDER_ID=<id> in your .env file."
        )
        return []

    try:
        service = get_drive_service(GOOGLE_CREDENTIALS_FILE)
        download_dir = Path(SAMPLE_PDF_DIR) / "gdrive_downloads"
        download_dir.mkdir(parents=True, exist_ok=True)

        all_files = _list_drive_files(service, GDRIVE_FOLDER_ID, recursive=GDRIVE_RECURSIVE)
        logger.info("Found %d file(s) in Google Drive folder.", len(all_files))

        paths: list[str] = []
        for f in all_files:
            dest = _download_drive_file(service, f, download_dir)
            if dest:
                paths.append(str(dest))

        return paths

    except RuntimeError as e:
        logger.error("Google Drive setup error: %s", e)
        return []
    except Exception as e:
        logger.error("Google Drive load failed: %s", e, exc_info=True)
        return []


def _list_drive_files(service, folder_id: str, recursive: bool = True) -> list[dict]:
    """
    Return a flat list of Drive file metadata dicts for all PDFs
    (and Google Docs/Sheets/Slides) in the given folder.
    """
    supported_mimes = " or ".join([
        f"mimeType='{_NATIVE_PDF_MIME}'",
        f"mimeType='{_GOOGLE_DOCS_MIME}'",
        f"mimeType='{_GOOGLE_SHEETS_MIME}'",
        f"mimeType='{_GOOGLE_SLIDES_MIME}'",
    ])
    query = (
        f"'{folder_id}' in parents "
        f"and ({supported_mimes}) "
        f"and trashed=false"
    )

    results = (
        service.files()
        .list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=100,
        )
        .execute()
    )
    files: list[dict] = results.get("files", [])

    # Handle pagination
    while "nextPageToken" in results:
        results = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=100,
                pageToken=results["nextPageToken"],
            )
            .execute()
        )
        files.extend(results.get("files", []))

    if recursive:
        # Find sub-folders and scan them too
        folder_query = (
            f"'{folder_id}' in parents "
            f"and mimeType='application/vnd.google-apps.folder' "
            f"and trashed=false"
        )
        sub_results = (
            service.files()
            .list(q=folder_query, fields="files(id, name)")
            .execute()
        )
        for sub in sub_results.get("files", []):
            logger.debug("Scanning sub-folder: %s (%s)", sub["name"], sub["id"])
            files.extend(_list_drive_files(service, sub["id"], recursive=True))

    return files


def _download_drive_file(service, file_meta: dict, dest_dir: Path) -> Path | None:
    """
    Download a single Drive file to dest_dir.
    Google Docs/Sheets/Slides are exported as PDF.
    Returns the local Path on success, None on failure.
    """
    from googleapiclient.http import MediaIoBaseDownload

    file_id = file_meta["id"]
    filename = file_meta["name"]
    mime = file_meta.get("mimeType", "")

    # Ensure filename ends with .pdf
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    dest = dest_dir / filename

    if dest.exists():
        logger.info("  [GDrive] Already downloaded: %s — skipping.", filename)
        return dest

    try:
        if mime in (_GOOGLE_DOCS_MIME, _GOOGLE_SHEETS_MIME, _GOOGLE_SLIDES_MIME):
            # Export native Google file as PDF
            request = service.files().export_media(fileId=file_id, mimeType="application/pdf")
        else:
            # Download binary PDF directly
            request = service.files().get_media(fileId=file_id)

        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        dest.write_bytes(buffer.getvalue())
        logger.info("  [GDrive] Downloaded: %s", filename)
        return dest

    except Exception as e:
        logger.error("  [GDrive] Failed to download '%s': %s", filename, e)
        return None


#  SOURCE: GMAIL ATTACHMENTS 

def _load_gmail() -> list[str]:
    """
    Download PDF attachments from matching Gmail messages.

    Search behaviour:
    - Uses GMAIL_SEARCH_QUERY from .env (default: shipping/invoice/freight with attachment).
    - Scans up to GMAIL_MAX_RESULTS messages.
    - Deduplicates by Gmail message ID so the same attachment is never re-downloaded.
    - Already-downloaded files (same name) are skipped.
    """
    try:
        service = get_gmail_service(GOOGLE_CREDENTIALS_FILE)
        download_dir = Path(SAMPLE_PDF_DIR) / "gmail_downloads"
        download_dir.mkdir(parents=True, exist_ok=True)

        logger.info("[Gmail] Searching with query: %s", GMAIL_SEARCH_QUERY)
        paths = _fetch_gmail_attachments(service, download_dir)
        return paths

    except RuntimeError as e:
        logger.error("Gmail setup error: %s", e)
        return []
    except Exception as e:
        logger.error("Gmail load failed: %s", e, exc_info=True)
        return []


def _fetch_gmail_attachments(service, download_dir: Path) -> list[str]:
    """
    Search Gmail for messages matching GMAIL_SEARCH_QUERY and download
    all PDF attachments.
    """
    paths: list[str] = []
    seen_message_ids: set[str] = set()

    #  List matching messages (paginate up to GMAIL_MAX_RESULTS) 
    response = (
        service.users()
        .messages()
        .list(userId="me", q=GMAIL_SEARCH_QUERY, maxResults=GMAIL_MAX_RESULTS)
        .execute()
    )
    messages = response.get("messages", [])
    logger.info("[Gmail] Found %d matching message(s).", len(messages))

    for msg_ref in messages:
        msg_id = msg_ref["id"]
        if msg_id in seen_message_ids:
            continue
        seen_message_ids.add(msg_id)

        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
        except Exception as e:
            logger.warning("[Gmail] Could not fetch message %s: %s", msg_id, e)
            continue

        subject = _get_header(msg, "Subject")
        sender  = _get_header(msg, "From")
        logger.debug("[Gmail] Processing email — From: %s | Subject: %s", sender, subject)

        attachments = _collect_parts(msg.get("payload", {}))
        for filename, attachment_id in attachments:
            dest = _download_gmail_attachment(
                service, msg_id, attachment_id, filename, download_dir
            )
            if dest:
                paths.append(str(dest))

    return paths


def _collect_parts(payload: dict) -> list[tuple[str, str]]:
    """
    Recursively collect (filename, attachmentId) pairs for PDF parts.
    Handles nested multipart messages.
    """
    results: list[tuple[str, str]] = []
    mime = payload.get("mimeType", "")
    filename = payload.get("filename", "")
    body = payload.get("body", {})

    if filename and filename.lower().endswith(".pdf"):
        attachment_id = body.get("attachmentId")
        if attachment_id:
            results.append((filename, attachment_id))

    # Recurse into multipart sub-parts
    for part in payload.get("parts", []):
        results.extend(_collect_parts(part))

    return results


def _download_gmail_attachment(
    service,
    message_id: str,
    attachment_id: str,
    filename: str,
    dest_dir: Path,
) -> Path | None:
    """Download a single Gmail attachment to dest_dir on disk."""
    dest = dest_dir / filename

    if dest.exists():
        logger.info("  [Gmail] Already downloaded: %s — skipping.", filename)
        return dest

    try:
        attachment = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data = base64.urlsafe_b64decode(attachment["data"])
        dest.write_bytes(data)
        logger.info("  [Gmail] Downloaded: %s", filename)
        return dest

    except Exception as e:
        logger.error("  [Gmail] Failed to download '%s': %s", filename, e)
        return None


def _get_header(msg: dict, name: str) -> str:
    """Extract a header value from a Gmail message dict."""
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""
