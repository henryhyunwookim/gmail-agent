"""
External Content Fetcher & Media Ingestion Engine (`src.content_fetcher`)
========================================================================

Purpose:
    Extracts, filters, and ingests external primary content linked within emails
    (e.g., full web articles, YouTube video transcripts, podcast show notes)
    to empower Gemini with rich source context beyond initial email previews.

Key Capabilities:
    1. Intelligent Link Filtering:
       Separates high-value content links from noise (unsubscribe, social share,
       tracking pixels, authentication, privacy policies).
    2. Multi-Modal Content Ingestion:
       - YouTube: Retrieves transcripts via `youtube_transcript_api` with multilingual
         fallback, or queries YouTube oEmbed / page metadata if transcripts are disabled.
       - Web Articles: Scrapes clean full text and structural headlines from blogs,
         Substack, Medium, and news publications.
       - Podcasts / Audio: Ingests episode titles, show notes, and transcripts.
    3. Resiliency & Timeouts:
       Enforces strict network budgets (8s timeout per link) and graceful degradation
       so external network failures never disrupt email processing.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup
import requests


# Recognized tracking parameters stripped during URL normalization
TRACKING_PARAMS: set[str] = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "source",
    "trk", "trkemail", "lipi", "midtoken", "midsig", "eid",
}

# Domains and path patterns that represent noise, auth barriers, or tracking
IGNORED_DOMAINS: set[str] = {
    "facebook.com", "twitter.com", "x.com", "instagram.com", "linkedin.com",
    "pinterest.com", "tiktok.com", "accounts.google.com", "apple.com/legal",
    "login.microsoftonline.com", "auth0.com", "okta.com", "appleid.apple.com",
    "id.atlassian.com", "login.live.com", "login.yahoo.com", "zoom.us/signin",
    "github.com/login",
}

IGNORED_SLUGS: list[str] = [
    "unsubscribe", "optout", "opt-out", "preferences", "manage-preferences",
    "email-preferences", "privacy", "privacy-policy", "terms", "terms-of-service",
    "cookie-policy", "tos", "login", "signin", "sign-in", "log-in", "signup",
    "sign-up", "register", "auth", "oauth", "sso", "authenticate", "session",
    "password-reset", "reset-password", "forgot-password", "verify-email", "2fa",
    "mfa", "checkout", "cart", "paywall", "subscribe", "subscription",
    "view-in-browser", "webversion", "redirect",
]

# Patterns in text or titles that indicate login walls, paywalls, or bot checks
AUTH_WALL_PATTERNS: list[str] = [
    "sign in", "log in", "login", "signin", "member login", "account login",
    "subscribe to read", "subscribers only", "paywall", "access denied",
    "403 forbidden", "401 unauthorized", "attention required! | cloudflare",
    "just a moment...", "security check", "please enable javascript",
    "create a free account", "join now to continue reading",
]


class ContentFetcher:
    """
    Fetches and processes external content referenced in email messages.
    """

    def __init__(self, timeout_seconds: int = 8) -> None:
        """
        Initializes the fetcher with configurable network timeouts.

        Args:
            timeout_seconds: Request timeout in seconds for HTTP operations.
        """
        self.timeout: int = timeout_seconds
        self.headers: dict[str, str] = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ja;q=0.8,ko;q=0.7,zh-CN;q=0.6",
        }

    # ==========================================================================
    # SECTION 1: URL Normalization & Link Filtering
    # ==========================================================================

    @staticmethod
    def normalize_url(url: str) -> str:
        """
        Cleans a URL by removing trailing slashes and marketing tracking parameters.

        Args:
            url: Raw HTTP(S) URL string.

        Returns:
            Normalized URL string.
        """
        parsed = urlparse(url.strip())
        query_dict = parse_qs(parsed.query)
        filtered_query = {k: v for k, v in query_dict.items() if k.lower() not in TRACKING_PARAMS}
        new_query = urlencode(filtered_query, doseq=True)
        cleaned = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.params,
            new_query,
            "",  # Remove fragment
        ))
        return cleaned

    @staticmethod
    def _is_supported_linkedin_content_url(url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path.lower()
        is_linkedin_host = host == "linkedin.com" or host.endswith(".linkedin.com")
        is_article_path = path.startswith((
            "/comm/pulse/",
            "/pulse/",
            "/comm/newsletters/",
            "/newsletters/",
            "/comm/posts/",
            "/posts/",
        ))
        return is_linkedin_host and is_article_path

    def is_candidate_content_url(self, url: str, anchor_text: str = "") -> bool:
        """
        Evaluates whether a URL points to substantive content rather than administrative noise
        or authentication barriers.

        Args:
            url: Target URL string.
            anchor_text: Visible anchor text for the link.

        Returns:
            True if the link is a viable content candidate.
        """
        if not url or not url.startswith(("http://", "https://")):
            return False

        url_lower = url.lower()
        anchor_lower = anchor_text.strip().lower()

        # Check ignored domains
        parsed = urlparse(url_lower)
        netloc = parsed.netloc
        if any(ignored in netloc for ignored in IGNORED_DOMAINS) and not self._is_supported_linkedin_content_url(url_lower):
            return False

        # Ignore obvious binary asset extensions
        if re.search(r"\.(png|jpg|jpeg|gif|webp|svg|ico|css|js|woff|woff2|pdf|zip|gz|tar|exe)$", parsed.path):
            return False

        # Check ignored URL slugs and auth query params
        for slug in IGNORED_SLUGS:
            if slug in url_lower or slug in anchor_lower:
                return False

        # Check auth redirect indicators in query string (e.g. redirect_to, next, return_url)
        if any(auth_param in parsed.query for auth_param in ("redirect_to", "next=", "return_url", "dest=")):
            return False

        return True

    def classify_url(self, url: str) -> str:
        """
        Identifies media category for an external link.

        Args:
            url: Target URL.

        Returns:
            Category identifier: 'youtube', 'podcast', or 'article'.
        """
        url_lower = url.lower()
        if "youtube.com" in url_lower or "youtu.be" in url_lower:
            return "youtube"
        if (
            "spotify.com/episode" in url_lower
            or "podcasts.apple.com" in url_lower
            or "buzzsprout.com" in url_lower
            or "podbean.com" in url_lower
            or url_lower.endswith((".mp3", ".m4a"))
        ):
            return "podcast"
        return "article"

    def extract_candidate_links(
        self,
        email_body_html: str = "",
        email_body_text: str = "",
        max_links: int = 2,
    ) -> list[dict[str, Any]]:
        """
        Scans email content for the top substantive content links.

        Scoring Heuristics:
            - Prioritizes YouTube, podcasts, and articles explicitly referenced with
              action keywords ('read more', 'full article', 'watch', 'listen').
            - De-duplicates candidate links.

        Args:
            email_body_html: Raw HTML content of the email.
            email_body_text: Plain text content of the email.
            max_links: Maximum candidate links to return.

        Returns:
            List of dictionaries with 'url', 'type', 'anchor_text', and 'score'.
        """
        candidates: list[dict[str, Any]] = []
        seen_candidates: dict[str, dict[str, Any]] = {}

        # Helper to register candidate
        def add_candidate(raw_url: str, text: str) -> None:
            if not self.is_candidate_content_url(raw_url, text):
                return
            norm_url = self.normalize_url(raw_url)

            link_type = self.classify_url(norm_url)
            score = 1.0

            # Boost high-intent anchor text
            text_lower = text.lower()
            intent_keywords = [
                "read more", "full article", "read post", "read on", "continue reading",
                "keep reading", "read on linkedin", "watch video", "watch now",
                "listen to", "episode", "view article", "deep dive", "read online",
            ]
            if any(kw in text_lower for kw in intent_keywords):
                score += 3.0
            if link_type == "youtube":
                score += 2.0
            elif link_type == "podcast":
                score += 1.5
            elif "/pulse/" in norm_url or "/comm/pulse/" in norm_url:
                score += 2.0

            if norm_url in seen_candidates:
                existing = seen_candidates[norm_url]
                if score > existing["score"]:
                    existing["score"] = score
                if text.strip() and not existing["anchor_text"]:
                    existing["anchor_text"] = text.strip()[:80]
                return

            candidate = {
                "url": norm_url,
                "type": link_type,
                "anchor_text": text.strip()[:80],
                "score": score,
            }
            seen_candidates[norm_url] = candidate
            candidates.append(candidate)

        # Step 1: Parse HTML DOM anchors if HTML is provided
        if email_body_html and ("<html" in email_body_html.lower() or "<a " in email_body_html.lower()):
            soup = BeautifulSoup(email_body_html, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                anchor = a_tag.get_text(separator=" ").strip()
                add_candidate(href, anchor)

        # Step 2: Fallback to plain text URL regex extraction
        if not candidates and email_body_text:
            url_pattern = r"https?://[^\s<>\"')\]]+"
            for match in re.finditer(url_pattern, email_body_text):
                found_url = match.group(0).rstrip(".,;!?:")
                add_candidate(found_url, "")

        # If specific articles are found, filter out generic newsletter series hub pages
        has_specific_article = any(
            "/pulse/" in c["url"] or "/comm/pulse/" in c["url"] for c in candidates
        )
        if has_specific_article:
            candidates = [
                c for c in candidates
                if not ("/newsletters/" in c["url"] or "/comm/newsletters/" in c["url"])
            ]

        # Sort by score descending and return top candidates
        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates[:max_links]

    # ==========================================================================
    # SECTION 2: Media & Content Ingestion
    # ==========================================================================

    @staticmethod
    def extract_youtube_video_id(url: str) -> str | None:
        """
        Extracts the 11-character YouTube video ID from various URL formats.

        Args:
            url: YouTube URL string.

        Returns:
            Video ID string if detected, or None.
        """
        patterns = [
            r"(?:v=|\/)([0-9A-Za-z_-]{11})(?:[&?]|$)",
            r"youtu\.be\/([0-9A-Za-z_-]{11})(?:[&?]|$)",
            r"(?:embed\/|v\/|shorts\/)([0-9A-Za-z_-]{11})(?:[&?]|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def fetch_youtube_content(self, url: str) -> dict[str, Any]:
        """
        Extracts transcript or video metadata for a YouTube URL.

        Args:
            url: YouTube video URL.

        Returns:
            Dictionary with 'title', 'content', 'type', 'success', and 'error'.
        """
        video_id = self.extract_youtube_video_id(url)
        if not video_id:
            return {
                "url": url,
                "type": "youtube",
                "title": "YouTube Video",
                "content": "",
                "success": False,
                "error": "Could not parse video ID from URL.",
            }

        # Step 1: Attempt transcript retrieval via youtube_transcript_api
        transcript_text = ""
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            transcript_obj = YouTubeTranscriptApi().fetch(
                video_id,
                languages=["en", "en-US", "ja", "ko", "zh-Hans", "zh-Hant"],
            )
            # Combine snippets into clean text
            snippets = [
                s.text if hasattr(s, "text") else s.get("text", "")
                for s in transcript_obj
            ]
            transcript_text = " ".join(snippets)
            if transcript_text:
                print(f"[FETCH] Fetched YouTube transcript for '{video_id}' ({len(transcript_text)} chars).")
        except Exception as transcript_err:
            print(f"[FETCH] YouTube transcript unavailable for '{video_id}': {transcript_err}")

        # Step 2: Query YouTube oEmbed metadata for title and author
        title = "YouTube Video"
        try:
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            resp = requests.get(oembed_url, timeout=self.timeout, headers=self.headers)
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("title", title)
                author = data.get("author_name", "")
                if author:
                    title = f"{title} (by {author})"
        except Exception:
            pass

        # Step 3: Combine metadata and transcript
        if transcript_text:
            content = f"Title: {title}\nVideo Transcript:\n{transcript_text[:15000]}"
            return {
                "url": url,
                "type": "youtube",
                "title": title,
                "content": content,
                "success": True,
                "error": None,
            }
        else:
            return {
                "url": url,
                "type": "youtube",
                "title": title,
                "content": f"Title: {title}\n(Full audio transcript could not be retrieved from YouTube; video title and metadata captured)",
                "success": True,
                "error": "Transcript unavailable",
            }

    def fetch_web_article(self, url: str) -> dict[str, Any]:
        """
        Scrapes readable article text from a web publication, blog, or news site,
        with strict defenses against login walls, paywalls, and authentication redirects.

        Args:
            url: Target web page URL.

        Returns:
            Dictionary with 'title', 'content', 'type', 'success', and 'error'.
        """
        try:
            resp = requests.get(
                url,
                timeout=self.timeout,
                headers=self.headers,
                allow_redirects=True,
            )
            if resp.status_code != 200:
                print(f"[FETCH] HTTP {resp.status_code} for '{url}' (skipping)")
                return {
                    "url": url,
                    "type": "article",
                    "title": "",
                    "content": "",
                    "success": False,
                    "error": f"HTTP {resp.status_code}",
                }

            # Guard 1: Detect redirect to login / authentication portal
            final_url = resp.url.lower()
            parsed_final = urlparse(final_url)
            if (
                any(auth_domain in parsed_final.netloc for auth_domain in IGNORED_DOMAINS)
                and not self._is_supported_linkedin_content_url(final_url)
            ):
                print(f"[FETCH] Skipping '{url}': Redirected to login/auth domain '{parsed_final.netloc}'.")
                return {
                    "url": url,
                    "type": "article",
                    "title": "",
                    "content": "",
                    "success": False,
                    "error": f"Redirected to authentication portal: {parsed_final.netloc}",
                }
            for slug in ("/login", "/signin", "/sign-in", "/log-in", "/auth/", "/sso", "/session"):
                if slug in parsed_final.path:
                    print(f"[FETCH] Skipping '{url}': Redirected to login path '{parsed_final.path}'.")
                    return {
                        "url": url,
                        "type": "article",
                        "title": "",
                        "content": "",
                        "success": False,
                        "error": f"Redirected to login path: {parsed_final.path}",
                    }

            # Guard 2: Verify HTML Content-Type
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return {
                    "url": url,
                    "type": "article",
                    "title": "",
                    "content": "",
                    "success": False,
                    "error": f"Unsupported Content-Type: {content_type}",
                }

            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract title
            title = ""
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            elif soup.find("meta", property="og:title"):
                title = soup.find("meta", property="og:title").get("content", "").strip()
            elif soup.find("h1"):
                title = soup.find("h1").get_text().strip()

            # Guard 3: Check title for login walls, paywalls, or bot challenges
            title_lower = title.lower()
            if any(pattern in title_lower for pattern in AUTH_WALL_PATTERNS):
                print(f"[FETCH] Skipping '{url}': Page title indicates auth/login barrier ('{title}').")
                return {
                    "url": url,
                    "type": "article",
                    "title": title,
                    "content": "",
                    "success": False,
                    "error": f"Encountered login wall or security check: '{title}'",
                }

            # Remove extraneous noise elements
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "svg", "noscript"]):
                tag.decompose()

            # Target article container if present
            article_tag = soup.find("article") or soup.find("main") or soup.find(class_=re.compile(r"post-content|entry-content|article-content|story-body"))
            if article_tag:
                text = article_tag.get_text(separator="\n", strip=True)
            else:
                # Fallback: collect all paragraphs
                paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
                text = "\n\n".join([p for p in paragraphs if len(p) > 20])

            # Collapse excess whitespace
            clean_text = re.sub(r"\n{3,}", "\n\n", text).strip()

            # Guard 4: Substantive length check
            if len(clean_text) < 120:
                print(f"[FETCH] Skipping '{url}': Content too short ({len(clean_text)} chars), likely paywalled or empty.")
                return {
                    "url": url,
                    "type": "article",
                    "title": title,
                    "content": "",
                    "success": False,
                    "error": f"Extracted content too short ({len(clean_text)} chars).",
                }

            # Guard 5: Check body snippet for subscription/login prompts
            sample_text = clean_text[:400].lower()
            paywall_phrases = (
                "please log in to continue", "sign in to read the full story",
                "already a subscriber? log in", "subscribe to get unlimited access",
                "create an account to continue reading", "please enable cookies",
            )
            if any(phrase in sample_text for phrase in paywall_phrases):
                print(f"[FETCH] Skipping '{url}': Body text indicates login/subscription requirement.")
                return {
                    "url": url,
                    "type": "article",
                    "title": title,
                    "content": "",
                    "success": False,
                    "error": "Article content requires subscription or login.",
                }

            print(f"[FETCH] Scraped article '{title[:40]}' ({len(clean_text)} chars).")

            return {
                "url": url,
                "type": "article",
                "title": title or "Web Article",
                "content": f"Title: {title}\nContent:\n{clean_text[:15000]}",
                "success": bool(clean_text),
                "error": None if clean_text else "No substantive text extracted.",
            }

        except Exception as e:
            print(f"[FETCH] Failed to fetch article from '{url}': {e}")
            return {
                "url": url,
                "type": "article",
                "title": "",
                "content": "",
                "success": False,
                "error": str(e),
            }

    def fetch_podcast_content(self, url: str) -> dict[str, Any]:
        """
        Extracts episode title, show notes, and transcript from a podcast URL.

        Args:
            url: Podcast episode URL.

        Returns:
            Dictionary with 'title', 'content', 'type', 'success', and 'error'.
        """
        # If direct audio stream, return metadata reference without attempting HTML scrape
        if url.lower().endswith((".mp3", ".m4a", ".wav", ".aac", ".ogg")):
            return {
                "url": url,
                "type": "podcast",
                "title": "Podcast Episode Audio",
                "content": f"Podcast Episode Audio Link: {url}",
                "success": True,
                "error": None,
            }
        # For web pages hosting podcasts, scrape the page for show notes
        return self.fetch_web_article(url)

    def fetch_content(self, url: str, link_type: str | None = None) -> dict[str, Any]:
        """
        Dispatches content extraction based on link category.

        Args:
            url: Target URL.
            link_type: Optional pre-classified type ('youtube', 'podcast', 'article').

        Returns:
            Standardized dictionary with 'url', 'type', 'title', 'content', 'success', and 'error'.
        """
        category = link_type or self.classify_url(url)
        if category == "youtube":
            return self.fetch_youtube_content(url)
        elif category == "podcast":
            return self.fetch_podcast_content(url)
        else:
            return self.fetch_web_article(url)
