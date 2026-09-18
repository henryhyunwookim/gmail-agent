import argparse
import os
import time
from datetime import datetime
from dotenv import load_dotenv

from src.auth import authenticate_gmail
from src.gmail_client import GmailClient
from src.summarizer import EmailSummarizer
from src.config import (
    get_max_emails,
    DEFAULT_MAX_EMAILS,
    get_interval_minutes,
    get_gemini_api_key,
)
from src.storage import record_run_log


def main(max_results=None, dry_run=False):
    load_dotenv()

    # Resolve batch limit via centralized configuration
    max_results = get_max_emails(max_results)

    execution_start = datetime.now()
    error_message = None
    stats = {
        "total": 0,
        "self_sent": 0,
        "purchase": 0,
        "already_summarized": 0,
        "processed": 0,
        "dry_run": dry_run,
    }

    if dry_run:
        print("[DRY-RUN] Running in dry-run mode. No emails will be forwarded or labels modified.")

    try:
        # Check for Gemini API Key (environment variable or Secret Manager)
        api_key = get_gemini_api_key()
        if not api_key:
            error_message = "Error: GEMINI_API_KEY could not be resolved from environment or Secret Manager ('gemini-api-key')."
            print(error_message)
            raise RuntimeError(error_message)

        # Authenticate Gmail
        print("Authenticating with Gmail (multi-PC portable resolver)...")
        creds = authenticate_gmail()
        client = GmailClient(creds)

        # Initialize Summarizer
        summarizer = EmailSummarizer(api_key)

        print(f"Checking for unread emails (limit: {max_results})...")
        messages = client.list_unread_messages(max_results=max_results)

        if not messages:
            print("No unread messages found.")
            stats["total"] = 0
        else:
            print(f"Found {len(messages)} unread emails. Processing...")
            stats["total"] = len(messages)

            # Get user's email address
            profile = client.service.users().getProfile(userId="me").execute()
            user_email = profile["emailAddress"]

            for msg in messages:
                print(f"Processing message ID: {msg['id']}")
                content = client.get_message_content(msg['id'])

                if not content:
                    continue

                # Check if this thread already has a summary
                thread_id = msg.get("threadId")
                if thread_id and client.thread_has_summary(thread_id, user_email):
                    stats["already_summarized"] += 1
                    print("Skipping - already has summary in thread")
                    continue

                # Filter out emails from self or agent
                sender_email = content["sender"]
                if "<" in sender_email:
                    sender_email = sender_email.split("<")[1].split(">")[0]
                sender_email = sender_email.strip("<> ")

                if user_email.lower() in sender_email.lower():
                    stats["self_sent"] += 1
                    print(f"Skipping email from self: {sender_email}")
                    continue

                # Filter out purchase/transactional emails
                if summarizer.is_purchase_email(content):
                    stats["purchase"] += 1
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
                if analysis.get("unsubscribe_link"):
                    unsubscribe_section = f"\n\nUnsubscribe Link: {analysis['unsubscribe_link']}\n"

                insights_section = ""
                if not is_ftchinese and analysis.get("sections") and len(analysis["sections"]) > 0:
                    insights_section = "\n\nInsights:\n"
                    for section in analysis["sections"]:
                        topic = section.get("topic", "Unknown")
                        insight = section.get("insight", "No insight provided")
                        insights_section += f"• {topic}: {insight}\n"

                translation_section = ""
                if is_ftchinese and analysis.get("learning_segments"):
                    translation_section = "\n\n=== CHINESE STUDY CORNER ===\n"
                    for i, segment in enumerate(analysis["learning_segments"], 1):
                        if i == 4:
                            break
                        translation_section += f"\n[Sentence {i}]\n"
                        translation_section += f"Original: {segment.get('original', '')}\n\n"
                        translation_section += f"Pinyin:   {segment.get('pinyin', '')}\n\n"
                        translation_section += f"English:  {segment.get('translation', '')}\n\n"
                        if segment.get("vocabulary"):
                            translation_section += "Vocabulary:\n"
                            for vocab in segment["vocabulary"]:
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

                if dry_run:
                    print(f"[DRY-RUN] Simulated summary generated for '{content['subject']}'. Skipping forward/label.")
                    stats["processed"] += 1
                else:
                    # Forward the original email with summary
                    print(f"Forwarding to {user_email}...")
                    client.forward_message(msg['id'], user_email, summary_text)

                    # Apply label based on action_required
                    label = "ActionRequired" if analysis.get("action_required") else "ReadLater"
                    client.add_label(msg['id'], label)
                    stats["processed"] += 1
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
        if dry_run:
            print("Mode: DRY-RUN (no modifications made)")
        print("=" * 50)

    except Exception as e:
        error_message = str(e)
        print(f"Error during execution: {error_message}")

    finally:
        execution_end = datetime.now()
        execution_time = execution_end.strftime("%Y-%m-%d %H:%M:%S")

        # 1. Send execution log email (only in non-dry-run mode)
        if not dry_run:
            try:
                if 'client' not in locals():
                    creds = authenticate_gmail()
                    client = GmailClient(creds)
                if 'user_email' not in locals():
                    profile = client.service.users().getProfile(userId='me').execute()
                    user_email = profile['emailAddress']

                print(f"\nSending execution log to {user_email}...")
                client.send_execution_log(
                    to=user_email,
                    stats=stats,
                    errors=error_message,
                    execution_time=execution_time,
                )
                print("Execution log sent successfully.")
            except Exception as log_error:
                print(f"Failed to send execution log email: {log_error}")

        # 2. Decoupled operational audit logging to GCS & Cloud Logging
        try:
            record_run_log({
                "status": "success" if error_message is None else "failed",
                "execution_time": execution_time,
                "duration_seconds": (datetime.now() - execution_start).total_seconds(),
                "stats": stats,
                "error": error_message,
            })
        except Exception as audit_err:
            print(f"Failed to persist audit log to GCS: {audit_err}")

    return {
        "success": error_message is None,
        "stats": stats,
        "error": error_message,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gmail AI Agent: Automatically summarize unread emails with Gemini AI.")
    parser.add_argument(
        "-n", "--max-emails",
        type=int,
        default=None,
        help=f"Maximum number of unread emails to process (defaults to MAX_EMAILS env var or {DEFAULT_MAX_EMAILS})",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Run continuously on a recurring interval (in minutes), e.g. --interval 30",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute in dry-run mode without forwarding emails or changing Gmail labels",
    )
    cli_args = parser.parse_args()

    interval_mins = get_interval_minutes(cli_args.interval)
    if interval_mins:
        print(f"Starting scheduled monitoring: running every {interval_mins} minutes (Press Ctrl+C to stop)...")
        try:
            while True:
                main(max_results=cli_args.max_emails, dry_run=cli_args.dry_run)
                print(f"\nNext run in {interval_mins} minutes. Waiting...")
                time.sleep(interval_mins * 60)
        except KeyboardInterrupt:
            print("\nMonitoring stopped by user.")
    else:
        main(max_results=cli_args.max_emails, dry_run=cli_args.dry_run)
