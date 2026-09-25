"""
AI Email Summarization & Cognitive Triage Engine (`src.summarizer`)
==================================================================

Purpose:
    Utilizes Google Gemini (Gemini 3.8 Flash) to analyze emails as an autonomous
    executive assistant tailored to the user's professional persona.

Agentic Capabilities:
    1. Unified Semantic Triage:
       Intelligently categorizes emails into actionable communications, deep-dive
       articles/newsletters, transactional receipts, service notifications, or noise,
       eliminating rigid, fragile keyword matching.
    2. Context-Aware Persona Alignment:
       Injects the user's professional profile, technical expertise, and priority
       focus areas into every briefing.
    3. Adaptive Language Learning & Detection:
       Dynamically detects text in the user's configured target language across email
       text and fetched articles, automatically generating structured language learning
       breakdowns (original, pronunciation/phonetics, vocabulary, English translation).
    4. RFC-Compliant Unsubscribe & Link Intelligence:
       Prioritizes RFC 2369 List-Unsubscribe headers over heuristics, with full DOM
       and regex fallback.
    5. External Content Ingestion:
       Discovers and ingests referenced articles, YouTube transcripts, and media notes.
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
from src.agent_memory import AgentMemoryManager
from src.content_fetcher import ContentFetcher
from src.persona import (
    build_persona_prompt_context,
    detect_chinese_content,
    detect_language_content,
    get_user_target_language,
    load_user_persona,
)


class EmailSummarizer:
    """
    Cognitive email analyzer and triage engine powered by Google Gemini AI.
    """

    # ==========================================================================
    # SECTION 1: Initialization & Model Configuration
    # ==========================================================================

    def __init__(self, api_key: str, model_name: str | None = None) -> None:
        """
        Initializes the Gemini GenerativeModel client, ContentFetcher, and AgentMemoryManager.

        Args:
            api_key: Valid Google Gemini AI API key.
            model_name: Optional Gemini model identifier. Defaults to
                GEMINI_MODEL environment variable or 'gemini-3.8-flash'.
        """
        genai.configure(api_key=api_key)
        selected_model = model_name or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self.model = genai.GenerativeModel(selected_model)
        self.content_fetcher = ContentFetcher()
        self.memory_manager = AgentMemoryManager()

    # ==========================================================================
    # SECTION 2: Unsubscribe Link Extraction (RFC 2369 + DOM + Regex)
    # ==========================================================================

    def extract_unsubscribe_link(
        self,
        email_body: str,
        list_unsubscribe: str | None = None,
    ) -> str | None:
        """
        Extracts an unsubscribe or preference link from RFC headers or email body.

        Resolution Cascade:
            1. RFC 2369 List-Unsubscribe header (standard HTTP URL).
            2. HTML DOM parsing: Scans <a> tags for multilingual keywords in text or href.
            3. Regex fallback: Matches URLs containing unsubscribe slugs in plain text.

        Args:
            email_body: Raw email body string (plain text or HTML).
            list_unsubscribe: Optional URL from RFC 2369 header.

        Returns:
            Extracted HTTP(S) unsubscribe URL string, or None if not found.
        """
        if list_unsubscribe and list_unsubscribe.startswith(("http://", "https://")):
            return list_unsubscribe

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

        # Step 1: Parse HTML DOM anchors if HTML is present
        if "<html" in email_body.lower() or "<body" in email_body.lower() or "<a " in email_body.lower():
            soup = BeautifulSoup(email_body, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                text = a_tag.get_text().strip().lower()
                href = a_tag["href"].lower()

                if any(kw in text for kw in keywords):
                    link = a_tag["href"]
                    break

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
                extracted = re.sub(r"[,;.)\]]+$", "", extracted)
                return extracted

        return None

    # ==========================================================================
    # SECTION 3: Semantic Triage & Heuristic Fallbacks
    # ==========================================================================

    def is_purchase_email(self, email_content: dict[str, Any]) -> bool:
        """
        Lightweight heuristic fallback to identify transactional e-commerce receipts.

        Primary classification is handled dynamically via `summarize()`.

        Args:
            email_content: Dictionary containing 'subject', 'sender', and 'body'.

        Returns:
            True if the email exhibits clear e-commerce receipt patterns.
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
            "주문", "결제", "영수증", "배송", "주문번호",       # Korean
            "注文", "請求書", "お支払い", "領収書", "配送",      # Japanese
            "订单", "发票", "交易", "发货", "购买",             # Chinese
        ]

        purchase_domains = [
            "amazon", "rakuten", "ebay", "paypal", "stripe", "shopify",
            "coupang", "naver.com", "shop.", "store.", "orders@", "noreply@", "no-reply@",
        ]

        is_commerce_sender = any(domain in sender_lower for domain in purchase_domains)
        keyword_count = sum(1 for kw in purchase_keywords if kw in subject_lower or kw in body_lower)

        return keyword_count >= 2 or (is_commerce_sender and keyword_count >= 1)

    # ==========================================================================
    # SECTION 4: AI Summarization, Triage & Chinese Study Generation
    # ==========================================================================

    def summarize(
        self,
        email_content: dict[str, Any],
        include_translation: bool | None = None,
    ) -> dict[str, Any]:
        """
        Performs end-to-end cognitive triage and executive briefing generation.

        Features:
            - Semantic Triage: Classifies email intent and determines optimal action
              (forward_briefing, skip_receipt, skip_noise).
            - Persona Context: Tailors insights to the user's technical focus and priority domains.
            - Adaptive Language Detection: Automatically creates language study segments
              whenever content in the user's configured target language is detected.
            - External Source Ingestion: Enriches preview emails with external articles
              or YouTube transcripts when relevant.

        Args:
            email_content: Dictionary containing 'subject', 'sender', 'body', 'html_body',
                and optional 'list_unsubscribe'.
            include_translation: Optional explicit override for language study breakdown.
                If None, dynamically detected from content.

        Returns:
            Dictionary containing structured summary, triage decisions, key insights,
            Chinese study segments, and external source metadata.
        """
        html_body = email_content.get("html_body", "")
        plain_body = email_content.get("body", "")
        list_unsub = email_content.get("list_unsubscribe")
        unsubscribe_link = self.extract_unsubscribe_link(html_body or plain_body, list_unsub)

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

        # Step 2: Body truncation
        max_chars = get_max_body_chars()
        truncated_body = plain_body[:max_chars]

        # Step 3: Adaptive Language Learning & Target Language Detection
        persona = load_user_persona()
        recipient_name = persona.get("name", "User")
        recipient_headline = persona.get("headline", "AI & Cloud Solutions Architect")
        target_lang = get_user_target_language(persona)

        detected_lang = False
        if target_lang:
            detected_lang = detect_language_content(
                truncated_body, target_lang, subject=email_content.get("subject", "")
            )
            if not detected_lang and fetched_sources:
                detected_lang = any(
                    detect_language_content(s.get("content", ""), target_lang) for s in fetched_sources
                )

        study_active = include_translation if include_translation is not None else detected_lang

        # Step 4: Construct Persona-Aware Cognitive Prompt with Accumulated Guidelines
        persona_context = build_persona_prompt_context(persona)
        learned_guidelines = self.memory_manager.get_formatted_hints(limit=8)

        lang_task_desc = (
            f", and generate a {target_lang} language study breakdown if {target_lang} content is present"
            if target_lang
            else ""
        )

        if target_lang:
            lang_study_rule = f"""3. Adaptive Language Study ({target_lang}):
   - If the email or external source contains text in {target_lang} (or covers {target_lang} learning), set "has_language_study": true. Provide 1 to 5 distinct sentences of actual {target_lang} text from the source in "learning_segments", with pronunciation/phonetics (e.g. Pinyin, Furigana/Romaji, or stress guide), key vocabulary, and accurate English translation.
   - If no {target_lang} text is present, set "has_language_study": false and "learning_segments": []."""
        else:
            lang_study_rule = """3. Language Study:
   - No target learning language is configured by the user. Set "has_language_study": false and "learning_segments": []."""

        prompt = f"""{persona_context}

{learned_guidelines}
TASK:
You are {recipient_name}'s executive AI email agent. Analyze this incoming email and any fetched external content.
Make an intelligent triage decision, produce a high-signal briefing calibrated to {recipient_name}'s expertise ({recipient_headline}){lang_task_desc}.

Email Subject: {email_content.get('subject', '')}
Email Sender: {email_content.get('sender', '')}
Email Content:
{truncated_body}
{external_context}

RESPONSE FORMAT:
You must respond with ONLY valid JSON in this exact structure (no markdown fences, no explanatory preamble):
{{
    "category": "newsletter_article | actionable_communication | transactional_receipt | service_notification | promotional_noise",
    "triage_action": "forward_briefing | skip_receipt | skip_noise",
    "executive_summary": "A substantive 3-5 sentence synthesis of the core narrative, relevant context, architectural/strategic stakes, and key developments.",
    "key_insights": [
        {{
            "topic": "Short topic name",
            "details": "Evidence-based technical analysis of mechanisms, trade-offs, systems implications, or strategic significance. Tailored for {recipient_headline}."
        }}
    ],
    "external_source_highlights": "Substantive evidence, data points, or arguments found in the fetched external sources that were missing from the email preview; return null if no external source was ingested.",
    "actionable_takeaways": [
        "Practical recommendation, follow-up consideration, or implication grounded in the text"
    ],
    "action_required": false,
    "reason": "Brief one-sentence explanation of why action is or is not required from {recipient_name}",
    "target_language": "{target_lang or ''}",
    "has_language_study": {str(study_active).lower()},
    "learning_segments": [
        {{
            "original": "{target_lang or 'Target language'} sentence from the email/article",
            "pronunciation": "Pronunciation/phonetics (e.g. Pinyin with tone marks, Furigana/Romaji, or stress guide)",
            "vocabulary": [
                {{"word": "vocabulary term", "pronunciation": "pronunciation", "english": "vocabulary word meaning"}}
            ],
            "translation": "Precise, natural English translation"
        }}
    ]
}}

TRIAGE & REASONING RULES:
1. Category & Triage Action:
   - "transactional_receipt" / "skip_receipt": Automated e-commerce purchase receipts, shipping notifications, order confirmations, payment transaction notices with no pending action needed.
   - "promotional_noise" / "skip_noise": Cold marketing pitches, unrequested promotional newsletters, low-value spam.
   - "newsletter_article" / "forward_briefing": Substantive technology newsletters, analytical articles, industry briefings, research insights.
   - "actionable_communication" / "forward_briefing": Direct personal/business correspondence, project requests, approvals, or messages requiring review or reply.
   - "service_notification": Automated cloud/platform alerts; set "forward_briefing" only if urgent/actionable, else "skip_noise".
2. Persona Calibration:
   - Highlight technical architecture, agentic workflows, serverless implications, digital transformation, and systemic trade-offs. Avoid shallow platitudes or repeating marketing taglines.
{lang_study_rule}
4. Action Required:
   - true ONLY if {recipient_name} needs to reply, make an approval, or take concrete action. Newsletters or informative reads are false.
5. Output ONLY the JSON object, with no prefix or suffix.
"""

        max_retries: int = 5
        retry_delay: int = 2

        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(prompt)
                text = response.text.strip()

                # Step 1: JSON block extraction
                extracted_json = text
                if "```json" in text:
                    extracted_json = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    extracted_json = text.split("```")[1].split("```")[0].strip()

                # Step 2: Parse standard JSON
                try:
                    result = json.loads(extracted_json)
                except json.JSONDecodeError:
                    json_match = re.search(r"(\{[\s\S]*\})", text)
                    if json_match:
                        try:
                            result = json.loads(json_match.group(1))
                        except json.JSONDecodeError:
                            if attempt == max_retries - 1:
                                raise ValueError(f"Could not parse JSON from Gemini response: {text[:100]}...")
                            print(f"[SUMMARIZER] JSON parsing failed on attempt {attempt + 1}. Retrying...")
                            continue
                    else:
                        if attempt == max_retries - 1:
                            raise ValueError(f"No JSON object detected in response: {text[:100]}...")
                        continue

                # Backward and forward compatibility key normalization
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

                # Default fallback for category & triage_action
                if "category" not in result:
                    result["category"] = "newsletter_article"
                if "triage_action" not in result:
                    result["triage_action"] = "forward_briefing"

                # Adaptive language study normalization
                if "has_language_study" not in result:
                    result["has_language_study"] = bool(result.get("has_chinese") or result.get("learning_segments"))
                result["has_chinese"] = bool(
                    result.get("has_language_study")
                    and (not target_lang or "chinese" in target_lang.lower() or "mandarin" in target_lang.lower())
                )
                result["target_language"] = target_lang

                # Normalize learning_segments fields
                normalized_segments = []
                for seg in result.get("learning_segments", []):
                    pron = seg.get("pronunciation") or seg.get("pinyin") or seg.get("phonetics") or ""
                    vocab = seg.get("vocabulary") or []
                    norm_vocab = []
                    for v in vocab:
                        w = v.get("word") or v.get("term") or ""
                        p = v.get("pronunciation") or v.get("pinyin") or ""
                        e = v.get("meaning") or v.get("english") or ""
                        norm_vocab.append({
                            "word": w,
                            "term": w,
                            "pinyin": p,
                            "pronunciation": p,
                            "english": e,
                            "meaning": e,
                        })
                    normalized_segments.append({
                        "original": seg.get("original", ""),
                        "pronunciation": pron,
                        "pinyin": pron,
                        "translation": seg.get("translation", ""),
                        "vocabulary": norm_vocab,
                    })
                result["learning_segments"] = normalized_segments

                result["unsubscribe_link"] = unsubscribe_link
                result["external_sources"] = fetched_sources

                # Record interaction for meta-reflection and self-improvement
                try:
                    self.memory_manager.record_interaction(
                        msg_id=email_content.get("id", ""),
                        sender=email_content.get("sender", ""),
                        subject=email_content.get("subject", ""),
                        category=result.get("category", "newsletter_article"),
                        triage_action=result.get("triage_action", "forward_briefing"),
                        action_required=result.get("action_required", False),
                    )
                except Exception:
                    pass

                return result

            except Exception as e:
                error_msg = str(e)
                print(f"[SUMMARIZER] Attempt {attempt + 1} failed: {error_msg}")
                if attempt < max_retries - 1:
                    if "429" in error_msg or "Resource exhausted" in error_msg:
                        print("[SUMMARIZER] Rate limit reached. Waiting 60 seconds before retrying...")
                        time.sleep(60)
                    else:
                        time.sleep(retry_delay * (attempt + 1))
                else:
                    traceback.print_exc()
                    print(f"[SUMMARIZER] Error summarizing email after {max_retries} attempts: {e}")
                    return {
                        "category": "service_notification",
                        "triage_action": "forward_briefing",
                        "executive_summary": "Error summarizing email.",
                        "summary": "Error summarizing email.",
                        "key_insights": [],
                        "sections": [],
                        "action_required": False,
                        "reason": f"AI processing failed: {str(e)}",
                        "unsubscribe_link": unsubscribe_link,
                        "external_sources": fetched_sources,
                        "target_language": target_lang,
                        "has_language_study": False,
                        "has_chinese": False,
                        "learning_segments": [],
                    }

        return {
            "category": "service_notification",
            "triage_action": "forward_briefing",
            "executive_summary": "Error summarizing email.",
            "summary": "Error summarizing email.",
            "key_insights": [],
            "sections": [],
            "action_required": False,
            "reason": "AI processing failed: Maximum retries exceeded.",
            "unsubscribe_link": unsubscribe_link,
            "external_sources": fetched_sources,
            "target_language": target_lang,
            "has_language_study": False,
            "has_chinese": False,
            "learning_segments": [],
        }
