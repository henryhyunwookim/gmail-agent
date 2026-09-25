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

from src.config import (
    get_enable_external_fetch,
    get_max_body_chars,
    get_max_external_links,
)
from src.content_fetcher import ContentFetcher


class EmailSummarizer:
    """
    Intelligent email analyzer powered by Google Gemini AI.
    """

    # ==========================================================================
    # SECTION 1: Initialization & Model Configuration
    # ==========================================================================

    def __init__(self, api_key: str, model_name: str | None = None) -> None:
        """
        Initializes the Gemini GenerativeModel client and ContentFetcher.

        Args:
            api_key: Valid Google Gemini AI API key.
            model_name: Optional Gemini model identifier. Defaults to
                GEMINI_MODEL environment variable or 'gemini-3.8-flash'.
        """
        genai.configure(api_key=api_key)
        selected_model = model_name or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self.model = genai.GenerativeModel(selected_model)
        self.content_fetcher = ContentFetcher()

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
        Generates an executive-grade, insightful newsletter briefing with deep context.

        Capabilities:
            - External Link Ingestion: Discovers and fetches candidate full articles,
              YouTube transcripts, and podcast show notes referenced in the email.
            - Expanded Context Limits: Processes up to 40,000 characters of email body.
            - Deep-Dive Intelligence: Generates an executive overview, detailed key insights,
              external source highlights, and actionable takeaways.
            - FTChinese Dual Mode: Provides both the comprehensive article briefing
              AND the educational sentence-by-sentence Chinese study breakdown.

        Args:
            email_content: Dictionary containing 'subject', 'sender', 'body', and optional 'html_body'.
            include_translation: Whether to generate educational FTChinese breakdown.

        Returns:
            Dictionary containing structured summary, key insights, external sources,
            action_required flag, and metadata.
        """
        # Resolve unsubscribe link from HTML or plain body
        html_body = email_content.get("html_body", "")
        plain_body = email_content.get("body", "")
        unsubscribe_link = self.extract_unsubscribe_link(html_body or plain_body)

        # Step 1: External content discovery & ingestion
        external_context = ""
        fetched_sources: list[dict[str, Any]] = []

        if get_enable_external_fetch():
            candidate_links = self.content_fetcher.extract_candidate_links(
                email_body_html=html_body,
                email_body_text=plain_body,
                max_links=get_max_external_links(),
            )
            for cand in candidate_links:
                url = cand["url"]
                ltype = cand["type"]
                print(f"[SUMMARIZER] Ingesting external {ltype} source: {url}")
                fetched = self.content_fetcher.fetch_content(url, ltype)
                if fetched.get("success") and fetched.get("content"):
                    fetched_sources.append(fetched)
                    external_context += (
                        f"\n\nExternal source ({ltype.upper()}): {url}\n"
                        f"{fetched.get('content', '')[:15000]}\n"
                        "End external source.\n"
                    )

        # Step 2: Body length resolution
        max_chars = get_max_body_chars()
        truncated_body = plain_body[:max_chars]

        # Step 3: Construct AI Prompt
        if include_translation:
            prompt = f"""Analyze this FTChinese email and any fetched article content. Write a concise but substantive briefing that preserves useful context, evidence, nuance, and implications, plus the requested Chinese study material.

Email Subject: {email_content.get('subject', '')}
Email Sender: {email_content.get('sender', '')}
Email Content:
{truncated_body}
{external_context}

IMPORTANT: You must respond with ONLY valid JSON in this exact structure (no markdown fences, no explanatory preamble):
{{
    "executive_summary": "A substantive 3-5 sentence synthesis of the narrative, relevant background, and stakes; reserve figures, examples, and detailed evidence for the insights.",
    "key_insights": [
        {{
            "topic": "Short topic",
            "details": "An evidence-based analysis of a distinct mechanism, tension, consequence, or implication, with enough context to explain why it matters."
        }}
    ],
    "actionable_takeaways": [
        "Optional practical recommendation or implication grounded in the source"
    ],
    "action_required": false,
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
- Keep distinct roles: the summary explains the narrative, context, and stakes; insights interpret concrete evidence and implications; takeaways state practical next steps.
- Reserve specific figures and examples for insights instead of repeating them in the summary. Each insight should add a different evidence-backed angle.
- Preserve decision-relevant context, figures, examples, caveats, and causal links. Reduce repetition, not analysis; do not pad to a target length.
- key_insights: Usually provide 2-4 substantive insights for a complex newsletter and fewer for a simple email. Give each 1-3 sentences with evidence and why it matters.
- actionable_takeaways: Return 0-3 useful recommendations that are distinct from the insights; use an empty array when none adds value.
- action_required: true if the email requires a reply, approval, or task from the recipient, false otherwise.
- reason: Brief one-sentence explanation.
- learning_segments: Cover up to the first 5 distinct sentences of main article text (exclude ads, promotions, and footer links). Include original Chinese, pinyin with tone marks, up to 3 vocabulary words, and English translation.
- Use only source-supported facts; do not infer details or inflate significance.
- Output ONLY the JSON object, nothing else.
"""
        else:
            prompt = f"""Analyze this email and any fetched external content. Produce a concise but substantive briefing: preserve meaningful context, evidence, nuance, and implications while removing repetition.

Email Subject: {email_content.get('subject', '')}
Email Sender: {email_content.get('sender', '')}
Email Content:
{truncated_body}
{external_context}

IMPORTANT: You must respond with ONLY valid JSON in this exact structure (no markdown fences, no explanatory preamble):
{{
    "executive_summary": "A substantive 3-5 sentence synthesis of the narrative, relevant background, and stakes; reserve figures, examples, and detailed evidence for the insights.",
    "key_insights": [
        {{
            "topic": "Short topic",
            "details": "An evidence-based analysis of a distinct mechanism, tension, consequence, or implication, with enough context to explain why it matters."
        }}
    ],
    "external_source_highlights": "A substantive synthesis of useful evidence, examples, arguments, or caveats found in fetched sources but missing from the email preview; otherwise null.",
    "actionable_takeaways": [
        "Optional practical recommendation or implication grounded in the source"
    ],
    "action_required": false,
    "reason": "Brief explanation of why action is or isn't required"
}}

Rules:
- Keep distinct roles: the summary explains the narrative, context, and stakes; insights interpret concrete evidence and implications; source highlights add material available only in fetched content; takeaways state practical next steps.
- Reserve specific figures and examples for insights instead of repeating them in the summary. Each insight should add a different evidence-backed angle.
- Preserve decision-relevant context, figures, examples, caveats, and causal links. Reduce repetition, not analysis; do not pad to a target length.
- key_insights: Usually provide 2-4 substantive insights for a complex newsletter and fewer for a simple email. Give each 1-3 sentences with evidence and why it matters.
- external_source_highlights: Explain what the fetched source adds beyond the email. Do not claim to have read a source unless its content was fetched successfully; otherwise return null.
- actionable_takeaways: Return 0-3 useful recommendations that are distinct from the insights; use an empty array when none adds value.
- action_required: true if the email requires a response, decision, or action from the recipient, false otherwise.
- reason: Brief one-sentence explanation.
- Use only source-supported facts; do not infer details or inflate significance.
- Output ONLY the JSON object, nothing else.
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
                except json.JSONDecodeError:
                    # Step 3: Regex fallback for JSON object boundaries
                    json_match = re.search(r"(\{[\s\S]*\})", text)
                    if json_match:
                        try:
                            result = json.loads(json_match.group(1))
                        except json.JSONDecodeError:
                            if attempt == max_retries - 1:
                                raise ValueError(f"Could not parse JSON from Gemini response: {text[:100]}...")
                            print(f"JSON parsing failed on attempt {attempt + 1}. Retrying...")
                            continue
                    else:
                        if attempt == max_retries - 1:
                            raise ValueError(f"No JSON object detected in response: {text[:100]}...")
                        continue

                # Normalize keys for backwards and forwards compatibility
                if "executive_summary" in result and "summary" not in result:
                    result["summary"] = result["executive_summary"]
                elif "summary" in result and "executive_summary" not in result:
                    result["executive_summary"] = result["summary"]

                if "key_insights" in result and "sections" not in result:
                    result["sections"] = [
                        {"topic": item.get("topic", "Insight"), "insight": item.get("details", "")}
                        for item in result.get("key_insights", [])
                    ]
                elif "sections" in result and "key_insights" not in result:
                    result["key_insights"] = [
                        {"topic": item.get("topic", "Insight"), "details": item.get("insight", "")}
                        for item in result.get("sections", [])
                    ]

                result["unsubscribe_link"] = unsubscribe_link
                result["external_sources"] = fetched_sources
                return result

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
                        "executive_summary": "Error summarizing email.",
                        "summary": "Error summarizing email.",
                        "key_insights": [],
                        "sections": [],
                        "action_required": False,
                        "reason": f"AI processing failed: {str(e)}",
                        "unsubscribe_link": unsubscribe_link,
                        "external_sources": fetched_sources,
                    }

        return {
            "executive_summary": "Error summarizing email.",
            "summary": "Error summarizing email.",
            "key_insights": [],
            "sections": [],
            "action_required": False,
            "reason": "AI processing failed: Maximum retries exceeded.",
            "unsubscribe_link": unsubscribe_link,
            "external_sources": fetched_sources,
        }
