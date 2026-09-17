import os
import time
from datetime import datetime
from dotenv import load_dotenv
from src.auth import authenticate_gmail
from src.gmail_client import GmailClient
from src.summarizer import EmailSummarizer
from src.config import get_max_emails, DEFAULT_MAX_EMAILS, get_interval_minutes

def main(max_results=None):
    load_dotenv()
    
    # Resolve batch limit via centralized configuration
    max_results = get_max_emails(max_results)

    execution_start = datetime.now()
    error_message = None
    stats = {
        'total': 0,
        'self_sent': 0,
        'purchase': 0,
        'already_summarized': 0,
        'processed': 0
    }
    
    try:
        # Check for Gemini API Key
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            error_message = "Error: GEMINI_API_KEY not found in environment variables."
            print(error_message)
            raise Exception(error_message)

        # Authenticate Gmail
        print("Authenticating with Gmail...")
        creds = authenticate_gmail()
        client = GmailClient(creds)
        
        # Initialize Summarizer
        summarizer = EmailSummarizer(api_key)
        
        print(f"Checking for unread emails (limit: {max_results})...")
        messages = client.list_unread_messages(max_results=max_results)
        
        if not messages:
            print("No unread messages found.")
            stats['total'] = 0
        else:
            print(f"Found {len(messages)} unread emails. Processing...")
            
            # Update statistics
            stats['total'] = len(messages)

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
                
                # Strip any stray brackets or spaces that might remain
                sender_email = sender_email.strip('<> ')
                
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

                
                # Check if this email is from FTChinese
                is_ftchinese = sender_email.lower().endswith("newsletter.ftchinese.com")
                
                # Summarize
                analysis = summarizer.summarize(content, include_translation=is_ftchinese)
                if is_ftchinese:
                    print(f"Action Required: {analysis.get('action_required', False)}")
                else:
                    print(f"Summary: {analysis.get('summary', 'No summary provided')}")
                    print(f"Action Required: {analysis.get('action_required', False)}")
                
                # Construct summary text for forwarding
                unsubscribe_section = ""
                if analysis.get('unsubscribe_link'):
                    unsubscribe_section = f"\n\nUnsubscribe Link: {analysis['unsubscribe_link']}\n"
                
                # Format insights section
                insights_section = ""
                if not is_ftchinese and analysis.get('sections') and len(analysis['sections']) > 0:
                    insights_section = "\n\nInsights:\n"
                    for section in analysis['sections']:
                        topic = section.get('topic', 'Unknown')
                        insight = section.get('insight', 'No insight provided')
                        insights_section += f"• {topic}: {insight}\n"
                
                # Format translation section for FTChinese
                translation_section = ""
                if is_ftchinese and analysis.get('learning_segments'):
                    translation_section = "\n\n=== CHINESE STUDY CORNER ===\n"
                    for i, segment in enumerate(analysis['learning_segments'], 1):
                        if i == 4:
                            break

                        translation_section += f"\n[Sentence {i}]\n"
                        translation_section += f"Original: {segment.get('original', '')}\n\n"
                        translation_section += f"Pinyin:   {segment.get('pinyin', '')}\n\n"
                        translation_section += f"English:  {segment.get('translation', '')}\n\n"
                        
                        if segment.get('vocabulary'):
                            translation_section += "Vocabulary:\n"
                            for vocab in segment['vocabulary']:
                                translation_section += f"  • {vocab.get('word', '')}: {vocab.get('pinyin', '')} - {vocab.get('english', '')}\n"
                            translation_section += "\n"
                    translation_section += "\n=============================\n"

                if is_ftchinese:
                    summary_text = f"""
=== EMAIL SUMMARY ===

Original Sender: {content['sender']}
Subject: {content['subject']}{translation_section}
Action Required: {'YES' if analysis.get('action_required', False) else 'NO'}
Reason: {analysis.get('reason', 'None')}{unsubscribe_section}
========================
"""
                else:
                    summary_text = f"""
=== EMAIL SUMMARY ===

Original Sender: {content['sender']}
Subject: {content['subject']}

Summary:
{analysis.get('summary', 'No summary provided')}{insights_section}
Action Required: {'YES' if analysis.get('action_required', False) else 'NO'}
Reason: {analysis.get('reason', 'None')}{unsubscribe_section}
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
        
    except Exception as e:
        error_message = str(e)
        print(f"Error during execution: {error_message}")
    
    finally:
        # Send execution log email
        try:
            execution_end = datetime.now()
            execution_time = execution_end.strftime("%Y-%m-%d %H:%M:%S")
            
            # Re-authenticate if needed for sending log
            if 'client' not in locals():
                creds = authenticate_gmail()
                client = GmailClient(creds)
            
            # Get user email
            if 'user_email' not in locals():
                profile = client.service.users().getProfile(userId='me').execute()
                user_email = profile['emailAddress']
            
            print(f"\nSending execution log to {user_email}...")
            client.send_execution_log(
                to=user_email,
                stats=stats,
                errors=error_message,
                execution_time=execution_time
            )
            print("Execution log sent successfully.")
        except Exception as log_error:
            print(f"Failed to send execution log: {log_error}")
    
    # Return results for caller (e.g., Cloud Run)
    return {
        'success': error_message is None,
        'stats': stats,
        'error': error_message
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gmail AI Agent: Automatically summarize unread emails with Gemini AI.")
    parser.add_argument(
        "-n", "--max-emails",
        type=int,
        default=None,
        help=f"Maximum number of unread emails to process (defaults to MAX_EMAILS env var or {DEFAULT_MAX_EMAILS})"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Run continuously on a recurring interval (in minutes), e.g. --interval 30 (defaults to RUN_INTERVAL_MINUTES env var)"
    )
    cli_args = parser.parse_args()
    
    # Check if continuous scheduling was requested
    interval_mins = get_interval_minutes(cli_args.interval)
    if interval_mins:
        print(f"Starting scheduled monitoring: running every {interval_mins} minutes (Press Ctrl+C to stop)...")
        try:
            while True:
                main(max_results=cli_args.max_emails)
                print(f"\nNext run in {interval_mins} minutes. Waiting...")
                time.sleep(interval_mins * 60)
        except KeyboardInterrupt:
            print("\nMonitoring stopped by user.")
    else:
        main(max_results=cli_args.max_emails)
