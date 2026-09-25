"""
User Persona & Cognitive Context Module (`src.persona`)
======================================================

Purpose:
    Maintains the persistent persona and technical context of the user
    (Henry Hyunwoo Kim, AI & Cloud Solutions Architect), synchronizing
    with the profile memory maintained by `linkedin-post-ghostwriter`
    via Google Cloud Storage and providing domain-aware guidance for
    email intelligence, relevance evaluation, and Chinese language study.

Architecture & Portability:
    1. Attempts to load live persona memory from Google Cloud Storage
       (`gs://<PROJECT_ID>-linkedin-memory/linkedin-ghostwriter/profile_memory.json`).
    2. Falls back to OS temporary cache if available.
    3. Guarantees 100% standalone operation via embedded baseline persona.
    4. Automatically detects Chinese language content to trigger educational
       language study breakdowns for the user.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Any

from src.config import get_project_id


# Canonical default persona baseline matching linkedin-post-ghostwriter
_DEFAULT_PERSONA: dict[str, Any] = {
    "name": "Henry Hyunwoo Kim",
    "headline": "AI & Cloud Solutions Architect | Digital Transformation & ODA",
    "about": (
        "Focusing on AI innovation, digital capacity building, and international "
        "development cooperation across Korea, Japan, and developing nations."
    ),
    "expertise_areas": [
        "Generative AI & Agentic Systems",
        "Cloud Architecture & Serverless Deployments",
        "International Cooperation & Digital ODA (KOICA/JICA/UN)",
        "AI Ethics, Policy, and Digital Inclusion",
    ],
    "language_focus": {
        "fluent": ["Korean", "English", "Japanese"],
        "learning": None,  # Configurable per user (e.g. 'Mandarin Chinese', 'Spanish', 'Japanese', None)
    },
    "prioritized_themes": [
        "Agentic AI workflows and system architectures",
        "Serverless, cloud computing, and distributed systems",
        "Enterprise technology strategy and digital transformation",
        "Digital ODA, international cooperation, and multilateral initiatives",
        "High-signal technical newsletters and deep-dive publications",
    ],
    "deprioritized_themes": [
        "Unsolicited sales pitches and cold outreach",
        "Routine transactional receipts and automated delivery notices",
        "Generic political polemics and unverified rumors",
        "Shallow motivational posts without technical or practical substance",
    ],
}

# Local OS temp cache path (zero workspace clutter)
_LOCAL_PERSONA_CACHE: str = os.path.join(
    tempfile.gettempdir(), "linkedin_ghostwriter_profile_memory.json"
)

# In-memory runtime cache
_CACHED_PERSONA: dict[str, Any] | None = None


def load_user_persona() -> dict[str, Any]:
    """
    Loads user persona memory with GCS, local temp cache, and embedded fallback.

    Resolution Cascade:
        1. In-memory process cache.
        2. Google Cloud Storage (`gs://<PROJECT_ID>-linkedin-memory/linkedin-ghostwriter/profile_memory.json`).
        3. Local OS temp file (`linkedin_ghostwriter_profile_memory.json`).
        4. Canonical default persona baseline.

    Returns:
        Structured dictionary containing user profile, expertise, and priorities.
    """
    global _CACHED_PERSONA
    if _CACHED_PERSONA is not None:
        return _CACHED_PERSONA

    project_id = get_project_id()
    bucket_name = os.getenv("GHOSTWRITER_BUCKET_NAME") or (
        f"{project_id}-linkedin-memory" if project_id else None
    )
    blob_path = "linkedin-ghostwriter/profile_memory.json"

    loaded_memory: dict[str, Any] | None = None

    # Step 1: Try GCS SDK (if running on Cloud Run or with IAM credentials)
    if bucket_name:
        try:
            from google.cloud import storage

            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            if blob.exists():
                data = blob.download_as_text(encoding="utf-8")
                loaded_memory = json.loads(data)
                print(f"[PERSONA] Loaded live persona from GCS: gs://{bucket_name}/{blob_path}")
        except Exception:
            pass

    # Step 2: Try gcloud CLI fallback (developer workstations)
    if loaded_memory is None and bucket_name:
        try:
            is_win = sys.platform == "win32"
            cmd = ["gcloud", "storage", "cat", f"gs://{bucket_name}/{blob_path}"]
            res = subprocess.run(
                cmd, capture_output=True, text=True, check=True, timeout=8, shell=is_win
            )
            if res.stdout.strip():
                loaded_memory = json.loads(res.stdout)
                print(f"[PERSONA] Loaded persona via gcloud storage CLI.")
        except Exception:
            pass

    # Step 3: Try OS temp cache
    if loaded_memory is None and os.path.exists(_LOCAL_PERSONA_CACHE):
        try:
            with open(_LOCAL_PERSONA_CACHE, "r", encoding="utf-8") as f:
                loaded_memory = json.load(f)
                print(f"[PERSONA] Loaded persona from local temp cache.")
        except Exception:
            pass

    # Step 4: Synthesize persona with baseline defaults
    persona = dict(_DEFAULT_PERSONA)
    if loaded_memory and isinstance(loaded_memory, dict):
        profile = loaded_memory.get("profile", {})
        if profile.get("name"):
            persona["name"] = profile["name"]
        if profile.get("headline"):
            persona["headline"] = profile["headline"]
        if profile.get("about"):
            persona["about"] = profile["about"]
        if profile.get("expertise_areas"):
            persona["expertise_areas"] = profile["expertise_areas"]

        if profile.get("language_focus"):
            persona["language_focus"] = profile["language_focus"]
        elif profile.get("languages"):
            persona["language_focus"] = profile["languages"]

        # Incorporate recent covered topics if available
        post_history = loaded_memory.get("post_history", [])
        if post_history:
            recent_topics = [
                p.get("topic") for p in post_history[-6:] if p.get("topic")
            ]
            if recent_topics:
                persona["recent_covered_topics"] = recent_topics

    _CACHED_PERSONA = persona
    return _CACHED_PERSONA


def get_user_target_language(persona: dict[str, Any] | None = None) -> str | None:
    """
    Resolves the user's active language learning goal across config and persona.

    Resolution Priority:
        1. Explicit system environment variable or config (`TARGET_LEARNING_LANGUAGE`).
        2. User's persona memory (`persona['language_focus']['learning']` or `persona['target_language']`).
        3. None (language learning disabled / standard briefing mode).

    Returns:
        The target language name (e.g. 'Mandarin Chinese', 'Spanish', 'Japanese') or None.
    """
    from src.config import get_target_learning_language

    env_target = get_target_learning_language()
    if env_target:
        return env_target

    p = persona if persona is not None else load_user_persona()
    lang_focus = p.get("language_focus") or p.get("languages") or {}
    learning = lang_focus.get("learning") or p.get("target_language")
    if learning and str(learning).strip().lower() not in ("none", "false", "off", "disable", "disabled"):
        return str(learning).strip()

    return None


def build_persona_prompt_context(persona: dict[str, Any] | None = None) -> str:
    """
    Renders the persona into a concise, high-signal system instruction context
    for Gemini to evaluate email relevance, calibrate tone, and extract insights.

    Returns:
        Formatted persona context string for LLM prompts.
    """
    p = persona if persona is not None else load_user_persona()
    name = p.get("name", "User")
    headline = p.get("headline", "AI & Cloud Solutions Architect")
    about = p.get("about", "")
    expertise_bullets = "\n".join(f"- {area}" for area in p.get("expertise_areas", []))
    priorities_bullets = "\n".join(f"- {theme}" for theme in p.get("prioritized_themes", []))

    target_lang = get_user_target_language(p)
    lang_line = (
        f"- Active Language Learning Goal: {target_lang}"
        if target_lang
        else "- Active Language Learning Goal: None (General Briefing Mode)"
    )

    return f"""USER PROFILE & CONTEXT:
Recipient: {name}
Role: {headline}
Background: {about}

Core Technical Focus Areas:
{expertise_bullets}

High-Priority Themes:
{priorities_bullets}

Language Interests:
{lang_line}
"""


def detect_language_content(
    text: str, target_language: str | None, subject: str = ""
) -> bool:
    """
    Intelligently determines whether an email or external article contains
    substantive text in the user's configured target learning language.

    Supports:
        - Chinese / Mandarin: CJK ideographs (\u4e00-\u9fff), newsletter markers.
        - Japanese: Hiragana / Katakana (\u3040-\u30ff).
        - Korean: Hangul syllables (\uac00-\ud7af).
        - Spanish, French, German, Italian, etc.: Character diacritics & common lexicon.
        - None / Disabled: Returns False immediately.

    Args:
        text: Email body or article text.
        target_language: The user's active learning language (e.g. 'Mandarin Chinese', 'Spanish').
        subject: Email subject line.

    Returns:
        True if the text contains substantive content matching the target language.
    """
    if not target_language or target_language.lower() in ("none", "false", "off", "disable", "disabled"):
        return False

    combined = f"{subject}\n{text[:4000]}"
    if not combined.strip():
        return False

    lang_lower = target_language.lower()

    # Case 1: Chinese / Mandarin
    if "chinese" in lang_lower or "mandarin" in lang_lower or "zhongwen" in lang_lower:
        cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", combined))
        kana_chars = len(re.findall(r"[\u3040-\u30ff]", combined))
        chinese_markers = [
            "ftchinese", "caixin", "scmp", "中文", "汉语", "学中文", "每日中文",
            "chinese edition", "newsletter.ftchinese.com",
        ]
        has_marker = any(m in combined.lower() for m in chinese_markers)
        if has_marker and cjk_chars >= 8:
            return True
        if cjk_chars >= 18 and cjk_chars > (kana_chars * 2):
            return True
        return False

    # Case 2: Japanese
    if "japanese" in lang_lower or "nihongo" in lang_lower:
        kana_chars = len(re.findall(r"[\u3040-\u30ff]", combined))
        return kana_chars >= 15

    # Case 3: Korean
    if "korean" in lang_lower or "hangul" in lang_lower:
        hangul_chars = len(re.findall(r"[\uac00-\ud7af]", combined))
        return hangul_chars >= 15

    # Case 4: Spanish
    if "spanish" in lang_lower or "espanol" in lang_lower:
        spanish_chars = len(re.findall(r"[áéíóúüñ¿¡]", combined, re.IGNORECASE))
        spanish_markers = [" el ", " la ", " los ", " las ", " de ", " en ", " que ", " por ", " para "]
        marker_hits = sum(1 for m in spanish_markers if m in f" {combined.lower()} ")
        return spanish_chars >= 3 or marker_hits >= 4

    # Case 5: French
    if "french" in lang_lower or "francais" in lang_lower:
        french_chars = len(re.findall(r"[àâçéèêëîïôûùüÿœæ]", combined, re.IGNORECASE))
        french_markers = [" le ", " la ", " les ", " des ", " du ", " pour ", " avec ", " dans "]
        marker_hits = sum(1 for m in french_markers if m in f" {combined.lower()} ")
        return french_chars >= 3 or marker_hits >= 4

    # Case 6: German
    if "german" in lang_lower or "deutsch" in lang_lower:
        german_chars = len(re.findall(r"[äöüß]", combined, re.IGNORECASE))
        german_markers = [" der ", " die ", " das ", " und ", " in ", " den ", " von ", " zu ", " mit "]
        marker_hits = sum(1 for m in german_markers if m in f" {combined.lower()} ")
        return german_chars >= 3 or marker_hits >= 4

    # Generic fallback: if non-English target language is specified, allow LLM to evaluate if text exists
    return len(combined.strip()) > 50


def detect_chinese_content(text: str, subject: str = "") -> bool:
    """Backward-compatible wrapper for Chinese language detection."""
    return detect_language_content(text, "Mandarin Chinese", subject=subject)

