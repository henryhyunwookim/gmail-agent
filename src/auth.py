import os
import sys
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# If modifying these scopes, delete the file token.json.
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify'
]

def authenticate_gmail(force_interactive=False):
    """Shows basic usage of the Gmail API.
    Lists the user's Gmail labels.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json') and not force_interactive:
        try:
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        except Exception as e:
            print(f"Error loading token.json: {e}")
            creds = None

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("Attempting to refresh access token...")
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing token: {e}")
                creds = None
        
        if not creds:
            # Check if running in a cloud environment (no browser available)
            is_cloud = os.getenv('K_SERVICE') is not None  # Cloud Run sets this
            
            # Determine if running interactively
            is_interactive = sys.stdin and sys.stdin.isatty()
            
            if (not is_interactive or is_cloud) and not force_interactive:
                # Remove the invalid token.json so it doesn't cause loop errors
                if os.path.exists('token.json'):
                    try:
                        os.remove('token.json')
                        print("Removed invalid/expired token.json.")
                    except Exception as rm_err:
                        print(f"Could not remove token.json: {rm_err}")
                
                raise RuntimeError(
                    "\n" + "="*80 + "\n"
                    "GMAIL AGENT AUTHENTICATION ERROR: Token has expired and cannot be refreshed automatically.\n"
                    "\n"
                    "This usually happens because your Google Cloud project's OAuth Consent Screen is in 'Testing' mode.\n"
                    "Google automatically expires refresh tokens after 7 days for apps in 'Testing'.\n"
                    "\n"
                    "PERMANENT FIX:\n"
                    "1. Go to the Google Cloud Console: https://console.cloud.google.com/\n"
                    "2. Navigate to 'APIs & Services' > 'OAuth consent screen'.\n"
                    "3. Under 'Publishing status', click the 'PUBLISH APP' button to set it to 'In Production'.\n"
                    "   (You do NOT need to submit it for verification since it is only for your personal use).\n"
                    "4. Re-run this authentication manually in an interactive terminal to generate a permanent token:\n"
                    "   python src/auth.py\n"
                    "5. Follow the browser prompt to log in and authorize the app.\n"
                    "="*80 + "\n"
                )
            
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError("credentials.json not found. Please download it from Google Cloud Console and place it in the project root directory.")
            
            print("Starting local server for interactive authentication...")
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
            
        # Save the credentials for the next run
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
    except Exception as err:
        print(f"\nAuthentication failed: {err}")
        sys.exit(1)
