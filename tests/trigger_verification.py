import os
import sys
from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.auth import authenticate_gmail
from src.gmail_client import GmailClient
from src.summarizer import EmailSummarizer

def trigger_real_forward():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found")
        return

    # Authenticate Gmail
    creds = authenticate_gmail()
    client = GmailClient(creds)
    summarizer = EmailSummarizer(api_key)
    
    # Get user email
    profile = client.service.users().getProfile(userId='me').execute()
    user_email = profile['emailAddress']
    
    # Search for latest FTChinese email
    query = 'from:newsletter.ftchinese.com'
    print(f"Searching for latest FTChinese email for forwarding...")
    
    results = client.service.users().messages().list(
        userId='me', q=query, maxResults=1).execute()
    messages = results.get('messages', [])
    
    if not messages:
        print("No FTChinese emails found.")
        return
    
    msg_id = messages[0]['id']
    content = client.get_message_content(msg_id)
    
    print(f"Summarizing and translating: {content['subject']}")
    analysis = summarizer.summarize(content, include_translation=True)
    
    # Construct summary text (similar to main.py logic)
    unsubscribe_section = ""
    if analysis.get('unsubscribe_link'):
        unsubscribe_section = f"\n\nUnsubscribe Link: {analysis['unsubscribe_link']}\n"
    
    insights_section = ""
    if analysis.get('sections') and len(analysis['sections']) > 0:
        insights_section = "\n\nInsights:\n"
        for section in analysis['sections']:
            topic = section.get('topic', 'Unknown')
            insight = section.get('insight', 'No insight provided')
            insights_section += f"• {topic}: {insight}\n"
    
    translation_section = "\n\n=== CHINESE STUDY CORNER ===\n"
    if analysis.get('learning_segments'):
        for i, segment in enumerate(analysis['learning_segments'], 1):
            translation_section += f"\n[Segment {i}]\n"
            translation_section += f"Original: {segment.get('original', '')}\n\n"
            translation_section += f"Pinyin:   {segment.get('pinyin', '')}\n\n"
            translation_section += f"English:  {segment.get('translation', '')}\n\n"
            
            if segment.get('vocabulary'):
                translation_section += "Vocabulary:\n"
                for vocab in segment['vocabulary']:
                    translation_section += f"  • {vocab.get('word')}: {vocab.get('pinyin')} - {vocab.get('english')}\n"
                translation_section += "\n"
    translation_section += "\n=============================\n"

    summary_text = f"""
=== EMAIL SUMMARY (REFINED LEARNING VERIFICATION) ===

Original Sender: {content['sender']}
Subject: {content['subject']}

Summary:
{analysis['summary']}{insights_section}{translation_section}
Action Required: {'YES' if analysis['action_required'] else 'NO'}
Reason: {analysis['reason']}{unsubscribe_section}
========================
"""
    
    print(f"Forwarding to {user_email}...")
    client.forward_message(msg_id, user_email, summary_text)
    print("SUCCESS: Forwarded verification email. Please check your inbox.")

if __name__ == "__main__":
    trigger_real_forward()
