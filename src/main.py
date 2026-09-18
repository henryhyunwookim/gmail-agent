"""
Gmail Agent Main Execution Pipeline (`src.main`)
================================================

Purpose:
    Coordinates the end-to-end email monitoring and summarization pipeline.
    Connects to the Gmail API, ingests unread messages, applies intelligent
    filtering (self-sent, duplicate summaries, purchase receipts), generates
    concise summaries via Gemini 3.8 Flash, forwards summaries back into the
    original email thread, applies labels, and records audit telemetry.

Execution Modes:
    1. Single-Shot Execution (Default / Cloud Run Trigger):
       `python -m src.main` or `python -m src.main --max-emails 10`
    2. Dry-Run Mode (Simulation without Forwarding or Labeling):
       `python -m src.main --dry-run`
    3. Continuous Local Monitoring Loop:
       `python -m src.main --interval 15` (runs every 15 minutes)

Prerequisites & Dependencies:
    - Google Cloud Project with Secret Manager, Cloud Storage, and Gmail API enabled.
    - Authenticated OAuth credentials (auto-resolved via `src.auth`).
    - Gemini API key (auto-resolved via `src.config`).
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from typing import Any, Optional

from dotenv import load_dotenv

from src.auth import authenticate_gmail
from src.config import (
    DEFAULT_MAX_EMAILS,
    get_gemini_api_key,
    get_interval_minutes,
    get_max_emails,
)
from src.gmail_client import GmailClient
from src.storage import record_run_log
from src.summarizer import EmailSummarizer


# ==============================================================================
# SECTION 1: Core Execution Pipeline
# ==============================================================================

def main(max_results: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    """
    Executes a single processing run of the Gmail AI Agent.

    Pipeline Stages:
        1. Configuration & Limit Resolution: Determines batch size from override/env.
        2. Authentication & Client Binding: Resolves credentials and initializes clients.
        3. Inbox Ingestion: Queries unread emails up to the batch limit.
        4. Intelligent Filtering: Skips self-sent, already-summarized, and purchase emails.
        5. AI Analysis: Summarizes email bodies with Gemini 3.8 Flash.
        6. Forwarding & Labeling: Embeds summary in-thread and tags ActionRequired/ReadLater.
        7. Audit & Execution Logging: Sends notification email and records log to GCS.

    Args:
        max_results: Optional batch limit override for unread emails.
        dry_run: If True, simulates AI summarization without sending emails or modifying labels.

    Returns:
        Dictionary with execution results:
            - `success` (bool): True if completed without unhandled exceptions.
            - `stats` (dict): Breakdown of processed, filtered, and total email counts.
            - `error` (str | None): Error message if an exception occurred.
    """
    load_dotenv()

    # Stage 1: Resolve batch limit via centralized configuration
    max_results = get_max_emails(max_results)

    execution_start = datetime.now()
    error_message: str | None = None
    stats: dict[str, Any] = {
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
        # Stage 2: Verify Gemini API Key
        api_key = get_gemini_api_key()
        if not api_key:
            error_message = (
                "Error: GEMINI_API_KEY could not be resolved from environment or "
                "Secret Manager ('gemini-api-key')."
            )
            print(error_message)
            raise RuntimeError(error_message)

        # Stage 2 (cont): Authenticate Gmail
        print("Authenticating with Gmail (multi-PC portable resolver)...")
        creds = authenticate_gmail()
        client = GmailClient(creds)

        # Stage 2 (cont): Initialize Summarizer
        summarizer = EmailSummarizer(api_key)

        # Stage 3: Query Inbox for Unread Messages
        print(f"Checking for unread emails (limit: {max_results})...")
        messages = client.list_unread_messages(max_results=max_results)

        if not messages:
            print("No unread messages found.")
            stats["total"] = 0
        else:
            print(f"Found {len(messages)} unread emails. Processing...")
            stats["total"] = len(messages)

            # Retrieve authenticated user's email address
            profile = client.service.users().getProfile(userId="me").execute()
            user_email = profile.get("emailAddress", "")

            # Stage 4: Iterate and Filter Messages
            for msg in messages:
                msg_id = msg["id"]
                print(f"\nProcessing message ID: {msg_id}")
                content = client.get_message_content(msg_id)

                if not content:
                    continue

                # Filter 4a: Thread redundancy check
                thread_id = msg.get("threadId")
                if thread_id and client.thread_has_summary(thread_id, user_email):
                    stats["already_summarized"] += 1
                    print("Skipping - thread already contains a forwarded summary.")
                    continue

                # Filter 4b: Self-sent check
                sender_email = content.get("sender", "")
                if "<" in sender_email:
                    sender_email = sender_email.split("<")[1].split(">")[0]
                sender_email = sender_email.strip("<> ")

                if user_email.lower() in sender_email.lower():
                    stats["self_sent"] += 1
                    print(f"Skipping email from self: {sender_email}")
                    continue

                # Filter 4c: Purchase & transactional receipt check
                if summarizer.is_purchase_email(content):
                    stats["purchase"] += 1
                    print(f"Skipping purchase email: {content.get('subject')}")
                    continue

                print(f"Subject: {content.get('subject')}")
                print(f"From: {content.get('sender')}")

                # Stage 5: AI Summarization & Chinese Study Generation
                is_ftchinese = sender_email.lower().endswith("newsletter.ftchinese.com")
                analysis = summarizer.summarize(content, include_translation=is_ftchinese)

                if is_ftchinese:
                    print(f"Action Required: {analysis.get('action_required', False)}")
                else:
                    print(f"Summary: {analysis.get('summary', 'No summary provided')}")
                    print(f"Action Required: {analysis.get('action_required', False)}")

                # Stage 6: Construct Forwarding Content
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

Original Sender: {content.get('sender')}
Subject: {content.get('subject')}{translation_section}
Action Required: {'YES' if analysis.get('action_required', False) else 'NO'}
Reason: {analysis.get('reason', 'None')}{unsubscribe_section}
========================
"""
                else:
                    summary_text = f"""
=== EMAIL SUMMARY ===

Original Sender: {content.get('sender')}
Subject: {content.get('subject')}

Summary:
{analysis.get('summary', 'No summary provided')}{insights_section}
Action Required: {'YES' if analysis.get('action_required', False) else 'NO'}
Reason: {analysis.get('reason', 'None')}{unsubscribe_section}
========================
"""

                # Stage 6 (cont): Dispatch Forward or Simulate Dry-Run
                if dry_run:
                    print(f"[DRY-RUN] Simulated summary generated for '{content.get('subject')}'. Skipping forward/label.")
                    stats["processed"] += 1
                else:
                    print(f"Forwarding to {user_email}...")
                    client.forward_message(msg_id, user_email, summary_text)

                    # Categorize message with appropriate Gmail label
                    label = "ActionRequired" if analysis.get("action_required") else "ReadLater"
                    client.add_label(msg_id, label)
                    stats["processed"] += 1
                    print("Done.")

                print("-" * 30)

        # Stage 7: Telemetry Console Report
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

        # Notification Stage: Send execution email log in live mode
        if not dry_run:
            try:
                if "client" not in locals():
                    creds = authenticate_gmail()
                    client = GmailClient(creds)
                if "user_email" not in locals():
                    profile = client.service.users().getProfile(userId="me").execute()
                    user_email = profile.get("emailAddress", "")

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

        # Cloud Logging & GCS Audit Stage
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


# ==============================================================================
# SECTION 2: Standalone CLI & Monitoring Loop Entry Point
# ==============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Gmail AI Agent: Automatically summarize unread emails with Gemini AI."
    )
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
