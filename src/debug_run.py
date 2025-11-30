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
    except Exception as e:
        print(f"Authentication failed: {e}", flush=True)

if __name__ == "__main__":
    main()
