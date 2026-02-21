import os
import sys
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.auth import authenticate_gmail
from src.gmail_client import GmailClient
from src.summarizer import EmailSummarizer

def test_real_ftchinese_emails():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found")
        return

    # Authenticate Gmail
    creds = authenticate_gmail()
    client = GmailClient(creds)
    summarizer = EmailSummarizer(api_key)
    
    # Search for FTChinese emails (not just unread ones)
    query = 'from:newsletter.ftchinese.com'
    print(f"Searching for emails with query: {query}")
    
    results = client.service.users().messages().list(
        userId='me', q=query, maxResults=3).execute()
    messages = results.get('messages', [])
    
    if not messages:
        print("No FTChinese emails found in your account.")
        return
    
    print(f"Found {len(messages)} FTChinese emails. Testing...")
    
    for msg in messages:
        print(f"\n--- Testing Message ID: {msg['id']} ---")
        content = client.get_message_content(msg['id'])
        
        if not content:
            print("Failed to get message content.")
            continue
            
        print(f"Subject: {content['subject']}")
        
        # Test summarization with translation
        print("Processing with translation...")
        analysis = summarizer.summarize(content, include_translation=True)
        
        print("\nSUMMARY:")
        print(analysis.get('summary'))
        
        print("\nPINYIN (Snippet):")
        pinyin = analysis.get('pinyin', '')
        print(pinyin[:200] + "..." if len(pinyin) > 200 else pinyin)
        
        print("\nENGLISH TRANSLATION (Snippet):")
        translation = analysis.get('english_translation', '')
        print(translation[:200] + "..." if len(translation) > 200 else translation)
        
        if analysis.get('pinyin') and analysis.get('english_translation'):
            print("\nSUCCESS for this email.")
        else:
            print("\nFAILURE: Missing pinyin or English translation.")

if __name__ == "__main__":
    test_real_ftchinese_emails()
