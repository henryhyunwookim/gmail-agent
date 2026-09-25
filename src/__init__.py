"""
Gmail Agent Core Package (`src`)
================================

This package contains the core business logic, authentication handlers,
cloud storage integration, Gemini AI analysis engine, and Flask HTTP webhook
for the Gmail Agent service running locally and on Google Cloud Run.

Modules:
    - `agent_memory`: Self-improving memory, feedback harvesting, and prompt reflection.
    - `app`: Flask web server entrypoint invoked by Google Cloud Run.
    - `auth`: Multi-PC zero-setup OAuth 2.0 authentication and token resolution.
    - `config`: Centralized single source of truth for defaults and environment settings.
    - `content_fetcher`: External content extraction (articles, YouTube transcripts, podcasts).
    - `gmail_client`: Gmail REST API v1 client, MIME message builder, and label manager.
    - `main`: End-to-end execution pipeline, intelligent filtering, and CLI runner.
    - `persona`: User persona context, expertise themes, and adaptable language detection.
    - `storage`: Cloud audit logging and GCS state persistence without workspace pollution.
    - `summarizer`: Gemini cognitive triage, adaptive language study segmenter, and link extractor.
"""
from __future__ import annotations

__all__ = [
    "agent_memory",
    "app",
    "auth",
    "config",
    "content_fetcher",
    "gmail_client",
    "main",
    "persona",
    "storage",
    "summarizer",
]
