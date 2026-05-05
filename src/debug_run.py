import sys
print("Starting debug...", flush=True)

print("Importing os...", flush=True)
import os
print("Importing time...", flush=True)
import time
print("Importing dotenv...", flush=True)
from dotenv import load_dotenv
print("Importing auth...", flush=True)
from auth import authenticate_gmail
print("Importing gmail_client...", flush=True)
from gmail_client import GmailClient
print("Importing summarizer...", flush=True)
from summarizer import EmailSummarizer

print("Imports done.", flush=True)

def main():
    print("Loading dotenv...", flush=True)
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not found", flush=True)
    else:
        print("GEMINI_API_KEY found", flush=True)
    
    print("Calling authenticate_gmail...", flush=True)
    try:
        creds = authenticate_gmail()
        print("Authentication successful", flush=True)
        
        print("Initializing GmailClient...", flush=True)
        client = GmailClient(creds)
        print("Fetching unread messages...", flush=True)
        messages = client.list_unread_messages(max_results=1)
        print(f"Successfully fetched {len(messages)} messages.", flush=True)
        
        print("Verifying Gemini API...", flush=True)
        summarizer = EmailSummarizer(api_key)
        # Just a simple test
        is_purchase = summarizer.is_purchase_email({'subject': 'Test Order', 'body': 'Your order #123', 'sender': 'amazon.com'})
        print(f"Summarizer check: {is_purchase}", flush=True)
        
        print("\nVerification COMPLETE. Ready for deployment.", flush=True)
    except Exception as e:
        print(f"Verification failed: {e}", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
