"""
core/google_auth.py — Shared Google OAuth2 helper
=================================================
Provides authenticated Google API service objects for both
Google Drive and Gmail using OAuth2 with token caching.

Scopes are chosen per-service so tokens stay minimal:
  - Drive  → drive.readonly
  - Gmail  → gmail.readonly

Token files are stored in the project root:
  - token_drive.json
  - token_gmail.json

Usage:
    from core.google_auth import get_drive_service, get_gmail_service
    drive   = get_drive_service()
    gmail   = get_gmail_service()
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Scope definitions  
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _authenticate(
    credentials_file: str,
    scopes: list[str],
    token_path: str,
) :
    """
    Perform OAuth2 flow or load cached credentials.

    Returns a google.oauth2.credentials.Credentials object,
    or raises RuntimeError on failure.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
    except ImportError as e:
        raise RuntimeError(
            "Google auth libraries missing. "
            "Run: pip install google-auth google-auth-oauthlib"
        ) from e

    creds: Optional[object] = None
    token_file = Path(token_path)

    #   1. Load cached token if it exists  
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), scopes)
            logger.debug("Loaded cached token from %s", token_path)
        except Exception as exc:
            logger.warning("Could not read token file %s: %s – will re-auth", token_path, exc)
            creds = None

    #   2. Refresh or run fresh OAuth flow  
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("Refreshed Google token for scopes: %s", scopes)
            except Exception as exc:
                logger.warning("Token refresh failed (%s) – running fresh auth flow.", exc)
                creds = None  # Fall through to fresh flow

        if not creds or not creds.valid:
            if not Path(credentials_file).exists():
                raise RuntimeError(
                    f"Google credentials file not found: {credentials_file}\n"
                    "Download it from https://console.cloud.google.com/apis/credentials "
                    "and place it in the project root."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, scopes)
            creds = flow.run_local_server(port=0)
            logger.info(" Google OAuth flow completed successfully.")

        #   3. Persist new / refreshed token  
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
        logger.debug("Saved Google token to %s", token_path)

    return creds


def get_drive_service(credentials_file: str = "credentials.json"):
    """
    Build and return an authenticated Google Drive v3 service.

    Args:
        credentials_file: Path to OAuth2 client credentials JSON.

    Returns:
        googleapiclient Resource object for Drive v3.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError as e:
        raise RuntimeError(
            "google-api-python-client not installed. "
            "Run: pip install google-api-python-client"
        ) from e

    creds = _authenticate(
        credentials_file=credentials_file,
        scopes=DRIVE_SCOPES,
        token_path="token_drive.json",
    )
    service = build("drive", "v3", credentials=creds)
    logger.info(" Google Drive service ready.")
    return service


def get_gmail_service(credentials_file: str = "credentials.json"):
    """
    Build and return an authenticated Gmail v1 service.

    Args:
        credentials_file: Path to OAuth2 client credentials JSON.

    Returns:
        googleapiclient Resource object for Gmail v1.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError as e:
        raise RuntimeError(
            "google-api-python-client not installed. "
            "Run: pip install google-api-python-client"
        ) from e

    creds = _authenticate(
        credentials_file=credentials_file,
        scopes=GMAIL_SCOPES,
        token_path="token_gmail.json",
    )
    service = build("gmail", "v1", credentials=creds)
    logger.info(" Gmail service ready.")
    return service
