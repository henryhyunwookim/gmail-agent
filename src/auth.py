import json
import os
import sys
import tempfile
from typing import Any, Dict, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from src.config import get_project_id, resolve_cloud_secret

# If modifying these scopes, update token in Secret Manager
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Secret Manager configuration keys
TOKEN_SECRET_NAME = os.getenv("GMAIL_TOKEN_SECRET_NAME", "gmail-agent-token")
CREDENTIALS_SECRET_NAME = os.getenv("GMAIL_CREDENTIALS_SECRET_NAME", "gmail-oauth-credentials")

# Temp cache path to avoid workspace root pollution
TEMP_TOKEN_CACHE = os.path.join(tempfile.gettempdir(), "gmail_agent_token.json")


def _is_cloud_run() -> bool:
    """Check if running on Cloud Run."""
    return os.getenv("K_SERVICE") is not None


def load_token_from_secret_manager() -> Optional[Dict[str, Any]]:
    """
    Load token content from Google Cloud Secret Manager using dual-mode resolution
    (Python SDK first, falling back to gcloud CLI).
    """
    project_id = get_project_id()
    if not project_id:
        print("[AUTH] WARNING: Could not determine project ID for Secret Manager.")
        return None

    raw_secret = resolve_cloud_secret(TOKEN_SECRET_NAME, project_id)
    if not raw_secret:
        print(f"[AUTH] Secret '{TOKEN_SECRET_NAME}' not found in project '{project_id}'.")
        return None

    try:
        token_data = json.loads(raw_secret)
        print(f"[AUTH] Successfully resolved token from Secret Manager ('{TOKEN_SECRET_NAME}').")
        return token_data
    except Exception as e:
        print(f"[AUTH] Error parsing token JSON from Secret Manager: {e}")
        return None


def save_token_to_secret_manager(creds: Credentials) -> bool:
    """Save refreshed or newly authorized token back to Secret Manager."""
    project_id = get_project_id()
    if not project_id:
        print("[AUTH] WARNING: Could not determine project ID for Secret Manager.")
        return False

    token_json = creds.to_json()

    # Method 1: Google Cloud Secret Manager SDK
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{project_id}/secrets/{TOKEN_SECRET_NAME}"
        client.add_secret_version(
            request={
                "parent": parent,
                "payload": {"data": token_json.encode("UTF-8")},
            }
        )
        print(f"[AUTH] Successfully saved token to Secret Manager ('{TOKEN_SECRET_NAME}').")
        return True
    except Exception:
        pass

    # Method 2: gcloud CLI fallback
    try:
        import subprocess
        is_win = sys.platform == "win32"
        # Write to temporary file for gcloud CLI input
        with open(TEMP_TOKEN_CACHE, "w", encoding="utf-8") as f:
            f.write(token_json)
        cmd = [
            "gcloud",
            "secrets",
            "versions",
            "add",
            TOKEN_SECRET_NAME,
            f"--data-file={TEMP_TOKEN_CACHE}",
            f"--project={project_id}",
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15, shell=is_win)
        print(f"[AUTH] Successfully uploaded token to Secret Manager via gcloud CLI.")
        return True
    except Exception as e:
        print(f"[AUTH] Failed to save token to Secret Manager: {e}")
        return False


def load_credentials_config() -> Optional[Dict[str, Any]]:
    """
    Loads OAuth client secrets config from local file, OS temp cache, or Secret Manager.
    """
    # 1. Local workspace file if explicitly present
    if os.path.exists("credentials.json"):
        try:
            with open("credentials.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 2. Secret Manager resolution
    project_id = get_project_id()
    if project_id:
        raw_creds = resolve_cloud_secret(CREDENTIALS_SECRET_NAME, project_id)
        if raw_creds:
            try:
                return json.loads(raw_creds)
            except Exception:
                pass

    return None


def authenticate_gmail(force_interactive: bool = False) -> Credentials:
    """
    Universal Gmail API authentication for ANY machine (local PC, laptop, or Cloud Run).
    Resolution priority:
      1. Local token.json (if explicitly placed)
      2. OS temp directory token cache
      3. Google Cloud Secret Manager ('gmail-agent-token')
    
    If token is expired:
      Refreshes in-memory and updates temp cache (workspace root is kept clean).
    
    If interactive login is required:
      Downloads client credentials from Secret Manager in-memory and opens browser.
    """
    creds = None
    on_cloud_run = _is_cloud_run()

    # --- 1. Load existing credentials ---
    if not force_interactive:
        # Check local file
        if os.path.exists("token.json"):
            try:
                creds = Credentials.from_authorized_user_file("token.json", SCOPES)
            except Exception as e:
                print(f"[AUTH] Error loading local token.json: {e}")
                creds = None

        # Check OS temp cache
        if not creds and os.path.exists(TEMP_TOKEN_CACHE):
            try:
                creds = Credentials.from_authorized_user_file(TEMP_TOKEN_CACHE)
            except Exception:
                creds = None

        # Check Secret Manager
        if not creds:
            token_data = load_token_from_secret_manager()
            if token_data:
                try:
                    token_scopes = token_data.get("scopes") or SCOPES
                    creds = Credentials.from_authorized_user_info(token_data, scopes=token_scopes)
                except Exception as e:
                    print(f"[AUTH] Error parsing token from Secret Manager: {e}")
                    creds = None

    # --- 2. Refresh or re-authenticate ---
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("[AUTH] Attempting in-memory token refresh...")
                creds.refresh(Request())
                print("[AUTH] Access token refreshed successfully.")
                # Save refreshed token to OS temp cache only (never polluting workspace)
                try:
                    with open(TEMP_TOKEN_CACHE, "w", encoding="utf-8") as f:
                        f.write(creds.to_json())
                except Exception:
                    pass
            except Exception as e:
                print(f"[AUTH] Error refreshing token: {e}")
                creds = None

        if not creds:
            is_interactive = sys.stdin and sys.stdin.isatty()
            if (not is_interactive or on_cloud_run) and not force_interactive:
                raise RuntimeError(
                    "\n" + "=" * 80 + "\n"
                    "GMAIL AGENT AUTHENTICATION ERROR: Token has expired or is missing.\n"
                    "\n"
                    "TO FIX (Zero-Setup / Multi-PC):\n"
                    "1. Ensure 'gcloud auth login' and 'gcloud config set project <PROJECT_ID>' are done.\n"
                    "2. Run: python -m src.auth\n"
                    "3. Complete browser login flow. The token will be saved to Secret Manager automatically.\n"
                    + "=" * 80 + "\n"
                )

            client_config = load_credentials_config()
            if not client_config:
                raise FileNotFoundError(
                    "OAuth client credentials not found in 'credentials.json' or Secret Manager "
                    f"('{CREDENTIALS_SECRET_NAME}'). Please configure it or run sync_secrets utility."
                )

            print("[AUTH] Starting local server for interactive authentication...")
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)

            # Save newly obtained token to temp cache and Secret Manager
            try:
                with open(TEMP_TOKEN_CACHE, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            except Exception:
                pass

            save_token_to_secret_manager(creds)
            print("[AUTH] Authentication complete! Token synchronized to Cloud Secret Manager.")

    return creds


if __name__ == "__main__":
    print("Gmail Agent - Interactive Re-authentication Tool")
    print("=" * 50)
    try:
        authenticate_gmail(force_interactive=True)
        print("\nSuccess! Token has been generated and synchronized to Secret Manager.")
    except Exception as err:
        print(f"\nAuthentication failed: {err}")
        sys.exit(1)
