"""
Gmail API Client & Message Construction (`src.gmail_client`)
============================================================

Purpose:
    Wraps Google APIs Client Library for Gmail (v1), providing high-level helpers
    for inbox querying, message parsing, thread redundancy checking, label manipulation,
    and MIME multipart message composition preserving original RFC 822 email threads.

Key Capabilities:
    1. Inbox Listing & Centralized Limits:
       Queries unread messages using `is:unread` up to the centralized limit (`get_max_emails`).
    2. Thread Summarization Inspection:
       Checks existing thread messages to prevent redundant duplicate summaries.
    3. Multipart MIME Construction:
       Embeds AI summaries as plain text while attaching the raw RFC 822 original message
       via `MIMEMessage`, setting `In-Reply-To`, `References`, and `threadId` headers.
    4. Label Management:
       Auto-creates and applies organizational labels (`ActionRequired`, `ReadLater`).
    5. Execution Reporting:
       Delivers structured run summaries directly to the user's inbox upon job completion.
"""
from __future__ import annotations

import base64
from email import message_from_bytes
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import re
from typing import Any, Optional

from bs4 import BeautifulSoup
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from src.config import get_max_emails


class GmailClient:
    """
    High-level interface for Gmail REST API operations.
    """

    # ==========================================================================
    # SECTION 1: Client Initialization
    # ==========================================================================

    def __init__(self, creds: Any) -> None:
        """
        Initializes the Gmail API service resource.

        Args:
            creds: Valid google.oauth2.credentials.Credentials instance.
        """
        self.service: Resource = build("gmail", "v1", credentials=creds)

    # ==========================================================================
    # SECTION 2: Message & Thread Ingestion
    # ==========================================================================

    def list_unread_messages(self, max_results: int | None = None) -> list[dict[str, Any]]:
        """
        Queries unread messages from the authenticated user's inbox.

        Args:
            max_results: Optional batch limit override. Defaults to centralized config.

        Returns:
            List of message dictionaries with 'id' and 'threadId'.
        """
        limit = get_max_emails(max_results)
        try:
            results = (
                self.service.users()
                .messages()
                .list(userId="me", q="is:unread -from:me", maxResults=limit)
                .execute()
            )
            messages = results.get("messages", [])
            return messages
        except HttpError as error:
            print(f"[GMAIL] HTTP Error querying messages: {error}")
            return []

    def thread_has_summary(self, thread_id: str, user_email: str) -> bool:
        """
        Determines whether a message thread already contains a forwarded summary.

        Prevents duplicate summaries when multiple unread replies arrive in a thread.

        Args:
            thread_id: Gmail thread ID to inspect.
            user_email: Authenticated user email address.

        Returns:
            True if any message in the thread is a forward sent by the user.
        """
        try:
            thread = self.service.users().threads().get(userId="me", id=thread_id).execute()
            messages = thread.get("messages", [])

            for msg in messages:
                # Ignore deleted messages residing in TRASH
                label_ids = msg.get("labelIds", [])
                if "TRASH" in label_ids:
                    continue

                headers = msg.get("payload", {}).get("headers", [])
                subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
                sender = next((h["value"] for h in headers if h["name"] == "From"), "")

                # Detect if an earlier forward was sent by the agent
                if "Fwd:" in subject and user_email.lower() in sender.lower():
                    return True
            return False
        except HttpError as error:
            print(f"[GMAIL] Error checking thread '{thread_id}': {error}")
            return False

    # ==========================================================================
    # SECTION 3: Content Parsing & Body Extraction
    # ==========================================================================

    @staticmethod
    def _html_to_markdown_text(html: str) -> str:
        """
        Converts raw HTML into clean text while preserving hyperlinks as [Anchor](URL).

        Args:
            html: Raw HTML string.

        Returns:
            Clean text representation with embedded Markdown links.
        """
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")

        # Decompose non-content and styling tags
        for tag in soup(["script", "style", "head", "meta", "svg", "noscript"]):
            tag.decompose()

        # Format hyperlinks cleanly as [Anchor Text](URL)
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            anchor_text = a_tag.get_text(separator=" ").strip()
            if href and not href.startswith(("mailto:", "tel:", "javascript:")):
                if anchor_text and anchor_text != href:
                    a_tag.replace_with(f" [{anchor_text}]({href}) ")
                else:
                    a_tag.replace_with(f" {href} ")

        # Format line breaks and block structures
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for block in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"]):
            block.insert_after("\n")

        raw_text = soup.get_text(separator=" ")
        # Clean whitespace and excess blank lines
        clean_text = re.sub(r"[ \t]+", " ", raw_text)
        clean_text = re.sub(r"\n\s*\n+", "\n\n", clean_text).strip()
        return clean_text

    def get_message_content(self, msg_id: str) -> dict[str, Any] | None:
        """
        Retrieves and decodes the subject, sender, body, and raw HTML of a message.

        Handles recursive multipart MIME structures (e.g. multipart/mixed containing
        multipart/alternative) and preserves hyperlinks during HTML-to-text conversion.

        Args:
            msg_id: Gmail message ID.

        Returns:
            Dictionary with 'id', 'subject', 'sender', 'body', and 'html_body' fields,
            or None on error.
        """
        try:
            message = self.service.users().messages().get(userId="me", id=msg_id).execute()
            payload = message.get("payload", {})
            headers = payload.get("headers", [])

            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No Subject")
            sender = next((h["value"] for h in headers if h["name"] == "From"), "Unknown Sender")

            plain_parts: list[str] = []
            html_parts: list[str] = []

            def _extract_mime_node(node: dict[str, Any]) -> None:
                mime_type = node.get("mimeType", "")
                data = node.get("body", {}).get("data")
                if data:
                    try:
                        decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                        if mime_type == "text/plain":
                            plain_parts.append(decoded)
                        elif mime_type == "text/html":
                            html_parts.append(decoded)
                    except Exception:
                        pass

                for child in node.get("parts", []):
                    _extract_mime_node(child)

            _extract_mime_node(payload)

            plain_text = "\n\n".join(plain_parts).strip()
            raw_html = "\n\n".join(html_parts).strip()

            # Choose the most substantive body representation
            if raw_html:
                markdown_text = self._html_to_markdown_text(raw_html)
                # If plain text is minimal or missing, or markdown text has more content/links
                if len(plain_text) < 150 or len(markdown_text) > len(plain_text):
                    effective_body = markdown_text
                else:
                    effective_body = plain_text
            else:
                effective_body = plain_text

            return {
                "id": msg_id,
                "subject": subject,
                "sender": sender,
                "body": effective_body,
                "html_body": raw_html,
            }
        except HttpError as error:
            print(f"[GMAIL] Error retrieving content for message '{msg_id}': {error}")
            return None

    # ==========================================================================
    # SECTION 4: Forwarding & MIME Composition
    # ==========================================================================

    def send_reply(self, to: str, subject: str, body: str) -> dict[str, Any] | None:
        """
        Sends a simple plain-text reply email.

        Args:
            to: Recipient email address.
            subject: Email subject.
            body: Plain-text body content.

        Returns:
            Gmail API message response dictionary, or None on failure.
        """
        try:
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
            body_dict = {"raw": raw}

            result = self.service.users().messages().send(userId="me", body=body_dict).execute()
            print(f"[GMAIL] Sent reply message ID: {result.get('id')}")
            return result
        except HttpError as error:
            print(f"[GMAIL] Error sending reply: {error}")
            return None

    def forward_message(
        self,
        original_msg_id: str,
        to: str,
        summary_text: str,
    ) -> dict[str, Any] | None:
        """
        Forwards a message with AI summary prepended and original email embedded,
        strictly preserving the Gmail conversation thread.

        MIME Composition:
            - Extracts the raw RFC 822 bytes of the original email.
            - Constructs a `multipart/mixed` container.
            - Part 1: AI summary plain text.
            - Part 2: `message/rfc822` containing the entire original email.
            - Sets `In-Reply-To`, `References`, and `threadId` headers for thread continuity.

        Args:
            original_msg_id: ID of the original message to forward.
            to: Target recipient email address.
            summary_text: AI-generated summary content to prepend.

        Returns:
            Gmail API message response dictionary, or None on failure.
        """
        try:
            # Step 1: Retrieve original raw email
            original = (
                self.service.users()
                .messages()
                .get(userId="me", id=original_msg_id, format="raw")
                .execute()
            )
            original_raw = base64.urlsafe_b64decode(original["raw"])
            original_email = message_from_bytes(original_raw)

            # Step 2: Assemble multipart container
            msg = MIMEMultipart()
            msg["To"] = to
            msg["Subject"] = "Fwd: " + (original_email.get("Subject", "No Subject"))

            # Step 3: Set threading headers
            if original_email.get("Message-ID"):
                msg["In-Reply-To"] = original_email.get("Message-ID")
                refs = original_email.get("References", "")
                msg["References"] = (refs + " " + original_email.get("Message-ID")).strip()

            # Step 4: Attach AI summary (plain text with explicit UTF-8 encoding)
            summary_part = MIMEText(summary_text, "plain", "utf-8")
            msg.attach(summary_part)

            # Step 5: Attach original email as message/rfc822
            original_msg_part = MIMEMessage(original_email)
            msg.attach(original_msg_part)

            # Step 6: Dispatch message bound to the original threadId
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            body = {
                "raw": raw,
                "threadId": original.get("threadId"),
            }

            result = self.service.users().messages().send(userId="me", body=body).execute()
            print(f"[GMAIL] Forwarded message ID: {result.get('id')} (Thread: {result.get('threadId', 'N/A')})")
            return result
        except HttpError as error:
            print(f"[GMAIL] Error forwarding message '{original_msg_id}': {error}")
            return None

    def mark_as_read(self, msg_id: str) -> None:
        """
        Removes the 'UNREAD' label from a message.

        Args:
            msg_id: Target Gmail message ID.
        """
        try:
            self.service.users().messages().modify(
                userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
            ).execute()
        except HttpError as error:
            print(f"[GMAIL] Error marking message '{msg_id}' as read: {error}")

    # ==========================================================================
    # SECTION 5: Label Management
    # ==========================================================================

    def get_or_create_label(self, label_name: str) -> str | None:
        """
        Retrieves or creates a user label by name.

        Args:
            label_name: Display name of the label (e.g. 'ActionRequired', 'ReadLater').

        Returns:
            Gmail label ID string, or None on failure.
        """
        try:
            results = self.service.users().labels().list(userId="me").execute()
            labels = results.get("labels", [])

            for label in labels:
                if label["name"] == label_name:
                    return label["id"]

            # Create label if absent
            label_object = {
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            }
            created_label = (
                self.service.users().labels().create(userId="me", body=label_object).execute()
            )
            print(f"[GMAIL] Created new label: '{label_name}' (ID: {created_label['id']})")
            return created_label["id"]
        except HttpError as error:
            print(f"[GMAIL] Error resolving label '{label_name}': {error}")
            return None

    def add_label(self, msg_id: str, label_name: str) -> None:
        """
        Applies a named label to a message.

        Args:
            msg_id: Target Gmail message ID.
            label_name: Label name to attach.
        """
        try:
            label_id = self.get_or_create_label(label_name)
            if label_id:
                self.service.users().messages().modify(
                    userId="me", id=msg_id, body={"addLabelIds": [label_id]}
                ).execute()
                print(f"[GMAIL] Applied label '{label_name}' to message '{msg_id}'.")
        except HttpError as error:
            print(f"[GMAIL] Error applying label '{label_name}' to message '{msg_id}': {error}")

    # ==========================================================================
    # SECTION 6: Execution Log Notification
    # ==========================================================================

    def send_execution_log(
        self,
        to: str,
        stats: dict[str, Any],
        errors: str | None = None,
        execution_time: str = "Unknown",
    ) -> dict[str, Any] | None:
        """
        Sends an operational execution summary email detailing batch counts and errors.

        Args:
            to: Recipient email address.
            stats: Dictionary of batch statistics (total, self_sent, purchase, processed, etc.).
            errors: Optional error string if failures occurred.
            execution_time: Timestamp string of execution.

        Returns:
            Gmail API message response dictionary, or None on failure.
        """
        try:
            status = "✅ SUCCESS" if not errors else "❌ FAILED"
            error_section = f"\n\n🚨 ERRORS:\n{errors}\n" if errors else ""

            body = f"""
Gmail Agent Execution Log
========================

Status: {status}
Execution Time: {execution_time}

📊 STATISTICS:
--------------
Total unread emails: {stats.get('total', 0)}
Filtered (self-sent): {stats.get('self_sent', 0)}
Filtered (purchase): {stats.get('purchase', 0)}
Filtered (already summarized): {stats.get('already_summarized', 0)}
Processed & forwarded: {stats.get('processed', 0)}
External sources ingested: {stats.get('external_sources_fetched', 0)}
{error_section}
========================

This is an automated execution log from your Gmail Agent running on Google Cloud Run.
"""
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = f"Gmail Agent Log - {status} - {execution_time}"
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
            body_data = {"raw": raw}

            result = self.service.users().messages().send(userId="me", body=body_data).execute()
            print(f"[GMAIL] Execution log sent. Message ID: {result.get('id')}")
            return result
        except HttpError as error:
            print(f"[GMAIL] Error sending execution log email: {error}")
            return None
