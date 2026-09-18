"""
AI Email Summarization & Analysis Engine (`src.summarizer`)
==========================================================

Purpose:
    Utilizes Google Gemini 3.8 Flash to analyze email content, generate structured
    concise summaries, extract key insights, detect required user actions, and provide
    educational Chinese language breakdowns for FTChinese newsletters.

Key Features:
    1. Multilingual Unsubscribe Link Extraction:
       Combines HTML DOM anchor inspection via BeautifulSoup with resilient regex patterns
       supporting English, Chinese, Japanese, Korean, Spanish, French, German, and Russian.
    2. Purchase / Transactional Email Filtering:
       Applies heuristic scoring across subject lines, body snippets, and known commerce
       sender domains (Amazon, PayPal, Shopify, etc.) to skip noise.
    3. Structured JSON Enforcement:
       Forces strict JSON schemas with multi-tiered JSON extraction fallbacks
       (code fence extraction -> JSON object regex matching).
    4. Resilient Exponential Backoff:
       Implements retry loops with backoff specifically handling transient HTTP 429
       rate limits and Vertex AI / Gemini API resource exhaustion.
"""
from __future__ import annotations

import json
import os
import re
import time
import traceback
from typing import Any, Optional

from bs4 import BeautifulSoup
import google.generativeai as genai


class EmailSummarizer:
    """
    Intelligent email analyzer powered by Google Gemini AI.
    """

    # ==========================================================================
    # SECTION 1: Initialization & Model Configuration
    # ==========================================================================

    def __init__(self, api_key: str, model_name: str | None = None) -> None:
        """
        Initializes the Gemini GenerativeModel client.

        Args:
            api_key: Valid Google Gemini AI API key.
            model_name: Optional Gemini model identifier. Defaults to
                GEMINI_MODEL environment variable or 'gemini-3.8-flash'.
        """
        genai.configure(api_key=api_key)
        selected_model = model_name or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self.model = genai.GenerativeModel(selected_model)

    # ==========================================================================
    # SECTION 2: Multilingual Unsubscribe Link Extraction
    # ==========================================================================

    def extract_unsubscribe_link(self, email_body: str) -> str | None:
        """
        Extracts an unsubscribe or preference management link from an email body.

        Extraction Strategy:
            1. HTML DOM parsing: Scans <a> tags for multilingual keywords in text or href.
            2. Regex fallback: Matches URLs containing unsubscribe keywords in plain text.

        Args:
            email_body: Raw email body string (plain text or HTML).

        Returns:
            The extracted HTTP(S) link string, or None if no link was detected.
        """
        # Multilingual unsubscribe keywords (lowercased for case-insensitive matching)
        keywords: list[str] = [
            "unsubscribe", "optout", "opt-out", "remove", "preferences",
            "退订", "取消订阅",                     # Chinese
            "darse de baja", "cancelar suscripción",  # Spanish
            "se désabonner", "désinscription",       # French
            "abmelden",                              # German
            "配信停止", "退会",                       # Japanese
            "수신거부", "구독취소",                    # Korean
            "annulla iscrizione", "cancellati",      # Italian
            "cancelar subscrição", "remover",        # Portuguese
            "отписаться",                            # Russian
        ]

        link: str | None = None

        # Step 1: Parse as HTML via BeautifulSoup if HTML tags are present
        if "<html" in email_body.lower() or "<body" in email_body.lower() or "<a " in email_body.lower():
            soup = BeautifulSoup(email_body, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                text = a_tag.get_text().strip().lower()
                href = a_tag["href"].lower()

                # Check if anchor display text matches any keyword
                if any(kw in text for kw in keywords):
                    link = a_tag["href"]
                    break

                # Check if URL itself contains common English unsubscribe slugs
                english_kws = ["unsubscribe", "optout", "opt-out", "remove"]
                if any(kw in href for kw in english_kws):
                    link = a_tag["href"]
                    break

        if link:
            return link

        # Step 2: Fallback to regex pattern matching for plain text bodies
        patterns = [
            r"https?://[^\s<>\"']+?unsubscribe[^\s<>\"']*",
            r"https?://[^\s<>\"']+?optout[^\s<>\"']*",
            r"https?://[^\s<>\"']+?opt-out[^\s<>\"']*",
            r"https?://[^\s<>\"']+?remove[^\s<>\"']*",
            r"https?://[^\s<>\"']+?preferences[^\s<>\"']*",
        ]

        for pattern in patterns:
            match = re.search(pattern, email_body, re.IGNORECASE)
            if match:
                extracted = match.group(0)
                # Strip trailing punctuation or HTML delimiters
                extracted = re.sub(r"[,;.)\]]+$", "", extracted)
                return extracted

        return None

    # ==========================================================================
    # SECTION 3: Transactional & Purchase Email Heuristics
    # ==========================================================================

    def is_purchase_email(self, email_content: dict[str, Any]) -> bool:
        """
        Determines whether an email is an automated receipt, order confirmation, or invoice.

        Heuristic Scoring:
            - Scans subject, first 500 characters of body, and sender address.
            - Filters if 2+ purchase keywords match OR 1+ keyword from a recognized e-commerce domain.

        Args:
            email_content: Dictionary containing 'subject', 'sender', and 'body' fields.

        Returns:
            True if the email matches transactional purchase characteristics.
        """
        subject_lower = email_content.get("subject", "").lower()
        body_lower = email_content.get("body", "")[:500].lower()
        sender_lower = email_content.get("sender", "").lower()

        purchase_keywords = [
            "order", "purchase", "receipt", "invoice", "payment", "transaction",
            "shipped", "delivery", "tracking", "confirmation", "your order",
            "thank you for your order", "order number", "tracking number",
            "order confirmation", "purchase confirmation", "order placed",
            "order received", "order summary", "billing", "charge",
        ]

        # Recognized commercial transaction domains and service addresses
        purchase_domains = [
            "amazon", "rakuten", "ebay", "paypal", "stripe", "shopify",
            "shop.", "store.", "orders@", "noreply@", "no-reply@",
        ]

        is_commerce_sender = any(domain in sender_lower for domain in purchase_domains)

        # Count occurrences of purchase terms across subject and body
        keyword_count = sum(1 for kw in purchase_keywords if kw in subject_lower or kw in body_lower)

        # Classification threshold
        return keyword_count >= 2 or (is_commerce_sender and keyword_count >= 1)

    # ==========================================================================
    # SECTION 4: AI Summarization & Chinese Study Generation
    # ==========================================================================

    def summarize(
        self,
        email_content: dict[str, Any],
        include_translation: bool = False,
    ) -> dict[str, Any]:
        """
        Summarizes email content using Gemini 3.8 Flash and evaluates required actions.

        Special Handling:
            - When `include_translation=True` (for FTChinese newsletters), generates a
              sentence-by-sentence Chinese study section (Original, Pinyin, English, Vocab).
            - When `include_translation=False`, generates a structured overview with
              topical insights and action detection.

        Args:
            email_content: Dictionary containing 'subject', 'sender', and 'body'.
            include_translation: Whether to generate educational FTChinese breakdown.

        Returns:
            Dictionary containing structured summary, action_required flag, and metadata.
        """
        unsubscribe_link = self.extract_unsubscribe_link(email_content.get("body", ""))

        if include_translation:
            prompt = f"""You are an intelligent email assistant specialized in Chinese language learning. Analyze the following FTChinese email and provide a structured learning breakdown.

Email Subject: {email_content.get('subject', '')}
Email Sender: {email_content.get('sender', '')}
Email Body:
{email_content.get('body', '')[:4000]}

IMPORTANT: You must respond with ONLY valid JSON in this exact format (no additional text):
{{
    "action_required": true,
    "reason": "Brief explanation of why action is or isn't required",
    "learning_segments": [
        {{
            "original": "...",
            "pinyin": "...",
            "vocabulary": [
                {{"word": "...", "pinyin": "...", "english": "..."}}
            ],
            "translation": "..."
        }}
    ]
}}

Rules:
- action_required: true if the email requires a response or action from the recipient, false otherwise
- reason: Brief explanation (one sentence)
- learning_segments: Break the email body down **sentence by sentence** for the first 5 distinct sentences of the main article content. Each segment should represent exactly one distinct sentence.
- EXCLUDE any promotional content, advertisements, newsletter subscription reminders, or FTChinese membership benefits from the learning_segments. Focus ONLY on the first 5 sentences of the actual article or main content.
- For each sentence in learning_segments, you MUST provide the original Chinese text, the pinyin with tone marks, a list of up to 3 key vocabulary words, and the English translation.
- Output ONLY the JSON object, nothing else
"""
        else:
            prompt = f"""You are an intelligent email assistant. Analyze the following email and provide a structured response.

Email Subject: {email_content.get('subject', '')}
Email Sender: {email_content.get('sender', '')}
Email Body:
{email_content.get('body', '')[:4000]}

IMPORTANT: You must respond with ONLY valid JSON in this exact format (no additional text):
{{
    "summary": "A concise 1-2 sentence overall summary of the email",
    "sections": [
        {{
            "topic": "Topic or theme of this section",
            "insight": "Key insight, information, or takeaway from this section"
        }}
    ],
    "action_required": true,
    "reason": "Brief explanation of why action is or isn't required"
}}

Rules:
- summary: Concise overall summary of the email (1-2 sentences)
- sections: Break down the email into logical sections.
- action_required: true if the email requires a response or action from the recipient, false otherwise
- reason: Brief explanation (one sentence)
- Output ONLY the JSON object, nothing else
"""

        max_retries: int = 5
        retry_delay: int = 2

        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(prompt)
                text = response.text.strip()

                # Step 1: Attempt JSON block extraction
                extracted_json = text
                if "```json" in text:
                    extracted_json = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    extracted_json = text.split("```")[1].split("```")[0].strip()

                # Step 2: Attempt standard JSON parsing
                try:
                    result = json.loads(extracted_json)
                    result["unsubscribe_link"] = unsubscribe_link
                    return result
                except json.JSONDecodeError:
                    # Step 3: Regex fallback for JSON object boundaries
                    json_match = re.search(r"(\{[\s\S]*\})", text)
                    if json_match:
                        try:
                            result = json.loads(json_match.group(1))
                            result["unsubscribe_link"] = unsubscribe_link
                            return result
                        except json.JSONDecodeError:
                            pass

                    if attempt == max_retries - 1:
                        raise ValueError(f"Could not parse JSON from Gemini response: {text[:100]}...")
                    else:
                        print(f"JSON parsing failed on attempt {attempt + 1}. Retrying...")
                        continue

            except Exception as e:
                error_msg = str(e)
                print(f"Attempt {attempt + 1} failed: {error_msg}")
                if attempt < max_retries - 1:
                    # Handle Vertex AI / Gemini 429 Rate Limit
                    if "429" in error_msg or "Resource exhausted" in error_msg:
                        print("Rate limit reached. Waiting 60 seconds before retrying...")
                        time.sleep(60)
                    else:
                        time.sleep(retry_delay * (attempt + 1))
                else:
                    traceback.print_exc()
                    print(f"Error summarizing email after {max_retries} attempts: {e}")
                    return {
                        "summary": "Error summarizing email.",
                        "action_required": False,
                        "reason": f"AI processing failed: {str(e)}",
                        "unsubscribe_link": unsubscribe_link,
                    }

        return {
            "summary": "Error summarizing email.",
            "action_required": False,
            "reason": "AI processing failed: Maximum retries exceeded.",
            "unsubscribe_link": unsubscribe_link,
        }
