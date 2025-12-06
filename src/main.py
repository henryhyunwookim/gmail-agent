import os
import time
from dotenv import load_dotenv
from src.auth import authenticate_gmail
from src.gmail_client import GmailClient
from src.summarizer import EmailSummarizer

def main():
    load_dotenv()
    
    # Check for Gemini API Key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in environment variables.")
        return

    # Authenticate Gmail
    print("Authenticating with Gmail...")
    creds = authenticate_gmail()
    client = GmailClient(creds)
    
    # Initialize Summarizer
    summarizer = EmailSummarizer(api_key)
    
    print("Checking for unread emails...")
    messages = client.list_unread_messages(max_results=50)  # Increased from 5 to 50
    
    if not messages:
        print("No unread messages found.")
        return
    
    print(f"Found {len(messages)} unread emails. Processing...")
    
    # Statistics
    stats = {
        'total': len(messages),
        'self_sent': 0,
        'purchase': 0,
        'already_summarized': 0,
        'processed': 0
    }


    # Get user's email address
    profile = client.service.users().getProfile(userId='me').execute()
    user_email = profile['emailAddress']
    
    for msg in messages:
        print(f"Processing message ID: {msg['id']}")
        content = client.get_message_content(msg['id'])
        
        if not content:
            continue
        
        # Check if this thread already has a summary
        thread_id = msg.get('threadId')
        if thread_id and client.thread_has_summary(thread_id, user_email):
            stats['already_summarized'] += 1
            print(f"Skipping - already has summary in thread")
            continue
        
        # Filter out emails from self or agent
        sender_email = content['sender']
        # Extract email from "Name <email@domain.com>" format
        if '<' in sender_email:
            sender_email = sender_email.split('<')[1].split('>')[0]
        
        if user_email.lower() in sender_email.lower():
            stats['self_sent'] += 1
            print(f"Skipping email from self: {sender_email}")
            continue
        
        # Filter out purchase/transactional emails
        if summarizer.is_purchase_email(content):
            stats['purchase'] += 1
            print(f"Skipping purchase email: {content['subject']}")
            continue
            
        print(f"Subject: {content['subject']}")
        print(f"From: {content['sender']}")

        
        # Summarize
        analysis = summarizer.summarize(content)
        print(f"Summary: {analysis['summary']}")
        print(f"Action Required: {analysis['action_required']}")
        
        # Construct summary text for forwarding
        unsubscribe_section = ""
        if analysis.get('unsubscribe_link'):
            unsubscribe_section = f"\n\nUnsubscribe Link: {analysis['unsubscribe_link']}\n"
        
        # Format insights section
        insights_section = ""
        if analysis.get('sections') and len(analysis['sections']) > 0:
            insights_section = "\n\nInsights:\n"
            for section in analysis['sections']:
                topic = section.get('topic', 'Unknown')
                insight = section.get('insight', 'No insight provided')
                insights_section += f"• {topic}: {insight}\n"
        
        summary_text = f"""
=== EMAIL SUMMARY ===

Original Sender: {content['sender']}
Subject: {content['subject']}

Summary:
{analysis['summary']}{insights_section}
Action Required: {'YES' if analysis['action_required'] else 'NO'}
Reason: {analysis['reason']}{unsubscribe_section}
========================
"""
        
        # Forward the original email with summary
        print(f"Forwarding to {user_email}...")
        client.forward_message(msg['id'], user_email, summary_text)
        
        # Apply label based on action_required
        label = 'ActionRequired' if analysis['action_required'] else 'ReadLater'
        client.add_label(msg['id'], label)
        
        stats['processed'] += 1
        
        # Mark as read
        # client.mark_as_read(msg['id']) # Uncomment to enable marking as read
        print("Done.")
        print("-" * 30)
    
    # Print summary statistics
    print("\n" + "=" * 50)
    print("SUMMARY STATISTICS")
    print("=" * 50)
    print(f"Total unread emails: {stats['total']}")
    print(f"Filtered (self-sent): {stats['self_sent']}")
    print(f"Filtered (purchase): {stats['purchase']}")
    print(f"Filtered (already summarized): {stats['already_summarized']}")
    print(f"Processed & forwarded: {stats['processed']}")
    print("=" * 50)


if __name__ == "__main__":
    main()
