#!/usr/bin/env python3
"""
Shared Google OAuth utility for the Website Builder pipeline.

Supports:
1. OAuth 2.0 token refresh (token.json)
2. Service Account credentials (service_account.json)
3. OAuth Installed App flow (credentials.json → browser login)

Usage:
    from execution.google_auth import get_credentials
    creds = get_credentials()
"""

import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()

DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


def get_credentials(scopes: list[str] = None):
    """
    Get valid Google OAuth2 credentials.

    Tries in order:
    1. Load token from GOOGLE_TOKEN_JSON env var (for Railway/cloud deployment)
    2. Load existing token from token.json and refresh if expired
    3. Load service account from GOOGLE_APPLICATION_CREDENTIALS env var
    4. Run OAuth installed app flow (opens browser for login)

    Args:
        scopes: OAuth scopes. Defaults to Sheets + Drive.

    Returns:
        Valid google.oauth2.credentials.Credentials object.

    Raises:
        SystemExit: If no credentials can be obtained.
    """
    if scopes is None:
        scopes = DEFAULT_SCOPES

    creds = None

    # 0. Write credential files from env vars if they exist (Railway deployment)
    _write_credentials_from_env()

    # 1. Try existing OAuth 2.0 token
    if os.path.exists("token.json"):
        try:
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_file("token.json", scopes)
        except Exception as e:
            print(f"Warning: Could not load token.json: {e}")
            creds = None

    # 2. Refresh expired token
    if creds and creds.expired and creds.refresh_token:
        try:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            # Save refreshed token
            with open("token.json", "w") as token:
                token.write(creds.to_json())
        except Exception as e:
            print(f"Warning: Could not refresh token: {e}")
            creds = None

    # 3. If no valid user creds, try service account or new OAuth flow
    if not creds or not creds.valid:
        creds_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")

        if os.path.exists(creds_file):
            with open(creds_file, "r") as f:
                content = json.load(f)

            if content.get("type") == "service_account":
                # Service Account
                print("Using Service Account credentials...")
                from google.oauth2.service_account import Credentials as SACredentials
                creds = SACredentials.from_service_account_file(creds_file, scopes=scopes)

            elif "installed" in content or "web" in content:
                # OAuth Installed App flow
                print("Starting OAuth login flow (opening browser)...")
                from google_auth_oauthlib.flow import InstalledAppFlow
                flow = InstalledAppFlow.from_client_secrets_file(creds_file, scopes)
                creds = flow.run_local_server(port=0)
                # Save token for future runs
                with open("token.json", "w") as token:
                    token.write(creds.to_json())
                print("OAuth token saved to token.json")
            else:
                print(f"Error: Unknown credential type in {creds_file}", file=sys.stderr)
                sys.exit(1)
        else:
            print(
                f"Error: No credentials found. Place credentials.json in project root "
                f"or set GOOGLE_APPLICATION_CREDENTIALS in .env",
                file=sys.stderr,
            )
            sys.exit(1)

    return creds


def _write_credentials_from_env():
    """Write Google credential files from environment variables (for cloud deployment).

    If GOOGLE_CREDENTIALS_JSON is set, writes it to credentials.json.
    If GOOGLE_TOKEN_JSON is set, writes it to token.json.
    """
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    token_json = os.getenv("GOOGLE_TOKEN_JSON", "")

    if creds_json and not os.path.exists("credentials.json"):
        with open("credentials.json", "w") as f:
            f.write(creds_json)
        print("Wrote credentials.json from GOOGLE_CREDENTIALS_JSON env var")

    if token_json and not os.path.exists("token.json"):
        with open("token.json", "w") as f:
            f.write(token_json)
        print("Wrote token.json from GOOGLE_TOKEN_JSON env var")
