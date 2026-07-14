import os
import sys
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# If modifying these scopes, delete the file token.json.
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify'
]

# Secret Manager configuration
SECRET_NAME = "gmail-agent-token"


def _get_project_id():
    """Get the GCP project ID from environment or metadata server."""
    project_id = os.getenv("GCP_PROJECT_ID")
    if project_id:
        return project_id
    # Fallback: on Cloud Run, query the metadata server
    try:
        import requests
        resp = requests.get(
            "http://metadata.google.internal/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"},
            timeout=2
        )
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
    return None


def _is_cloud_run():
    """Check if running on Cloud Run."""
    return os.getenv('K_SERVICE') is not None


def load_token_from_secret_manager():
    """Load token.json content from Google Cloud Secret Manager."""
    try:
        from google.cloud import secretmanager
        project_id = _get_project_id()
        if not project_id:
            print("WARNING: Could not determine project ID for Secret Manager.")
            return None

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{SECRET_NAME}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        token_data = response.payload.data.decode("UTF-8")
        print("Successfully loaded token from Secret Manager.")
        return json.loads(token_data)
    except Exception as e:
        print(f"Error loading token from Secret Manager: {e}")
        return None


def save_token_to_secret_manager(creds):
    """Save refreshed token back to Secret Manager as a new version."""
    try:
        from google.cloud import secretmanager
        project_id = _get_project_id()
        if not project_id:
            print("WARNING: Could not determine project ID for Secret Manager.")
            return

        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{project_id}/secrets/{SECRET_NAME}"
        token_json = creds.to_json()

        client.add_secret_version(
            request={
                "parent": parent,
                "payload": {"data": token_json.encode("UTF-8")},
            }
        )
        print("Successfully saved refreshed token to Secret Manager.")
    except Exception as e:
        print(f"Error saving token to Secret Manager: {e}")


def authenticate_gmail(force_interactive=False):
    """Authenticates with Gmail API.
    
    On Cloud Run: loads token from Secret Manager, refreshes if needed, saves back.
    Locally: uses token.json file as before.
    """
    creds = None
    on_cloud_run = _is_cloud_run()

    # --- Load existing credentials ---
    if on_cloud_run and not force_interactive:
        # Cloud Run: load from Secret Manager
        token_data = load_token_from_secret_manager()
        if token_data:
            try:
                creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            except Exception as e:
                print(f"Error parsing token from Secret Manager: {e}")
                creds = None
    elif os.path.exists('token.json') and not force_interactive:
        # Local: load from file
        try:
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        except Exception as e:
            print(f"Error loading token.json: {e}")
            creds = None

    # --- Refresh or re-authenticate ---
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("Attempting to refresh access token...")
                creds.refresh(Request())
                # Save the refreshed token
                if on_cloud_run:
                    save_token_to_secret_manager(creds)
                else:
                    with open('token.json', 'w') as token:
                        token.write(creds.to_json())
                        print("Saved refreshed token to token.json.")
            except Exception as e:
                print(f"Error refreshing token: {e}")
                creds = None
        
        if not creds:
            # Determine if we can do interactive auth
            is_interactive = sys.stdin and sys.stdin.isatty()
            
            if (not is_interactive or on_cloud_run) and not force_interactive:
                raise RuntimeError(
                    "\n" + "="*80 + "\n"
                    "GMAIL AGENT AUTHENTICATION ERROR: Token has expired and cannot be refreshed automatically.\n"
                    "\n"
                    "TO FIX (no redeployment needed):\n"
                    "1. On your local machine, run: python src/auth.py\n"
                    "2. Complete the browser login flow.\n"
                    "3. Upload the new token:  .\\deployment\\upload_token.ps1\n"
                    "\n"
                    "The Cloud Run service will automatically pick up the new token on the next run.\n"
                    + "="*80 + "\n"
                )
            
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError("credentials.json not found. Please download it from Google Cloud Console and place it in the project root directory.")
            
            print("Starting local server for interactive authentication...")
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
            
            # Save the credentials
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
                print("Successfully authenticated and saved token.json!")

    return creds

if __name__ == "__main__":
    print("Gmail Agent - Interactive Re-authentication Tool")
    print("=" * 50)
    try:
        authenticate_gmail(force_interactive=True)
        print("Success! token.json has been generated/updated.")
        print()
        print("Next step: upload the token to Secret Manager:")
        print("  .\\deployment\\upload_token.ps1")
    except Exception as err:
        print(f"\nAuthentication failed: {err}")
        sys.exit(1)
