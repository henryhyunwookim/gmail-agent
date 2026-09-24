"""
Configuration & Cloud Secret Resolution (`src.config`)
======================================================

Purpose:
    Serves as the centralized Single Source of Truth for system-wide defaults,
    runtime environment variables, Google Cloud Secret Manager resolution, and
    Google Cloud Storage (GCS) resource identifiers.

Resolution Priority Cascade:
    1. Explicit Function / CLI Call Overrides (highest precedence)
    2. Local or Container Environment Variables (`.env`, Cloud Run ENV)
    3. Google Cloud Secret Manager (`gemini-api-key`, `gmail-agent-token`, etc.)
    4. Canonical Codebase Defaults (fallback)

Multi-PC Portability Guarantee:
    When running on a machine without a local `.env` file, configuration
    gracefully auto-resolves from active Google Cloud SDK (`gcloud`) project
    settings and Google Cloud Secret Manager.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional
from dotenv import load_dotenv

# Automatically load environment variables from .env if present in workspace
load_dotenv()


# ==============================================================================
# SECTION 1: System Defaults (Single Source of Truth)
# ==============================================================================

# Default maximum number of unread emails processed per agent run
DEFAULT_MAX_EMAILS: int = 20

# Default Cloud Scheduler cron expression (05:00 and 17:00 daily)
DEFAULT_SCHEDULE: str = "0 5,17 * * *"

# Default timezone for scheduled execution
DEFAULT_TIMEZONE: str = "Asia/Seoul"

# Default flag whether to ingest external content (articles, YouTube transcripts, audio/podcasts)
DEFAULT_ENABLE_EXTERNAL_FETCH: bool = True

# Default maximum number of external candidate links fetched per email
DEFAULT_MAX_EXTERNAL_LINKS: int = 2

# Default maximum characters of email body passed to Gemini (expanded from 4,000 to 40,000)
DEFAULT_MAX_BODY_CHARS: int = 40000


# ==============================================================================
# SECTION 2: Runtime Parameters & Environment Overrides
# ==============================================================================

def get_max_emails(override: int | None = None) -> int:
    """
    Returns the effective maximum email batch limit.

    Resolution Priority:
        1. Explicit function/CLI override (if valid integer > 0).
        2. `MAX_EMAILS` environment variable (from `.env` or Cloud Run ENV).
        3. `DEFAULT_MAX_EMAILS` (single source of truth: 20).

    Args:
        override: Optional explicit batch limit passed via CLI or function call.

    Returns:
        The resolved integer email limit.
    """
    if override is not None:
        try:
            val = int(override)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass

    env_val = os.getenv("MAX_EMAILS")
    if env_val:
        try:
            val = int(env_val)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass

    return DEFAULT_MAX_EMAILS


def get_schedule(override: str | None = None) -> str:
    """
    Returns the effective cron schedule expression.

    Resolution Priority:
        1. Explicit override parameter (if non-empty string).
        2. `SCHEDULE` environment variable.
        3. `DEFAULT_SCHEDULE` (single source of truth: '0 5,17 * * *').

    Args:
        override: Optional cron expression override.

    Returns:
        The resolved cron schedule string.
    """
    if override and str(override).strip():
        return str(override).strip()
    env_val = os.getenv("SCHEDULE")
    if env_val and env_val.strip():
        return env_val.strip()
    return DEFAULT_SCHEDULE


def get_timezone(override: str | None = None) -> str:
    """
    Returns the effective timezone identifier.

    Resolution Priority:
        1. Explicit override parameter (if non-empty string).
        2. `TIMEZONE` environment variable.
        3. `DEFAULT_TIMEZONE` (single source of truth: 'Asia/Seoul').

    Args:
        override: Optional timezone identifier override (e.g. 'UTC', 'America/New_York').

    Returns:
        The resolved timezone identifier string.
    """
    if override and str(override).strip():
        return str(override).strip()
    env_val = os.getenv("TIMEZONE")
    if env_val and env_val.strip():
        return env_val.strip()
    return DEFAULT_TIMEZONE


def get_interval_minutes(override: int | None = None) -> int | None:
    """
    Returns optional interval in minutes for continuous local execution loop.

    Resolution Priority:
        1. Explicit override parameter (if valid integer > 0).
        2. `RUN_INTERVAL_MINUTES` environment variable.
        3. None (single-shot run; no continuous loop).

    Args:
        override: Optional loop interval in minutes.

    Returns:
        Integer interval minutes if scheduled loop requested, otherwise None.
    """
    if override is not None:
        try:
            val = int(override)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass
    env_val = os.getenv("RUN_INTERVAL_MINUTES")
    if env_val:
        try:
            val = int(env_val)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass
    return None


def get_enable_external_fetch(override: bool | None = None) -> bool:
    """
    Returns whether external link ingestion (articles, YouTube, podcasts) is enabled.

    Resolution Priority:
        1. Explicit override parameter (if provided).
        2. `ENABLE_EXTERNAL_FETCH` environment variable ('true', '1', 'yes').
        3. `DEFAULT_ENABLE_EXTERNAL_FETCH` (True).

    Args:
        override: Optional boolean override.

    Returns:
        Boolean indicating if external link content should be retrieved.
    """
    if override is not None:
        return bool(override)
    env_val = os.getenv("ENABLE_EXTERNAL_FETCH")
    if env_val is not None:
        return env_val.strip().lower() in ("true", "1", "yes", "on")
    return DEFAULT_ENABLE_EXTERNAL_FETCH


def get_max_external_links(override: int | None = None) -> int:
    """
    Returns the maximum number of external links fetched per email.

    Resolution Priority:
        1. Explicit override parameter (if valid integer >= 0).
        2. `MAX_EXTERNAL_LINKS` environment variable.
        3. `DEFAULT_MAX_EXTERNAL_LINKS` (2).

    Args:
        override: Optional integer limit override.

    Returns:
        Integer maximum link count.
    """
    if override is not None:
        try:
            val = int(override)
            if val >= 0:
                return val
        except (ValueError, TypeError):
            pass
    env_val = os.getenv("MAX_EXTERNAL_LINKS")
    if env_val:
        try:
            val = int(env_val)
            if val >= 0:
                return val
        except (ValueError, TypeError):
            pass
    return DEFAULT_MAX_EXTERNAL_LINKS


def get_max_body_chars(override: int | None = None) -> int:
    """
    Returns the maximum character length of email bodies passed to Gemini.

    Resolution Priority:
        1. Explicit override parameter (if valid integer > 0).
        2. `MAX_BODY_CHARS` environment variable.
        3. `DEFAULT_MAX_BODY_CHARS` (40,000 characters).

    Args:
        override: Optional integer character limit.

    Returns:
        Integer character threshold.
    """
    if override is not None:
        try:
            val = int(override)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass
    env_val = os.getenv("MAX_BODY_CHARS")
    if env_val:
        try:
            val = int(env_val)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass
    return DEFAULT_MAX_BODY_CHARS


# ==============================================================================
# SECTION 3: GCP Project & Cloud Secret Manager Resolution
# ==============================================================================

# Cache resolved project ID and secrets in memory during process runtime
_CACHED_PROJECT_ID: str | None = None
_CACHED_SECRETS: dict[str, str] = {}


def get_project_id() -> str | None:
    """
    Resolves the Google Cloud project ID across local and cloud environments.

    Resolution Cascade:
        1. In-memory runtime cache.
        2. Environment variables: `GCP_PROJECT_ID` or `GOOGLE_CLOUD_PROJECT`.
        3. Cloud Run / Compute Engine internal metadata server (if running in GCP).
        4. Local gcloud CLI active configuration (`gcloud config get-value project`).

    Returns:
        The resolved project ID string, or None if undetermined.
    """
    global _CACHED_PROJECT_ID
    if _CACHED_PROJECT_ID:
        return _CACHED_PROJECT_ID

    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id:
        _CACHED_PROJECT_ID = project_id.strip()
        return _CACHED_PROJECT_ID

    is_cloud = os.getenv("K_SERVICE") is not None

    # Step 2: Cloud Run / Compute Engine metadata server resolution (only if in cloud)
    if is_cloud or sys.platform != "win32":
        try:
            import requests
            resp = requests.get(
                "http://metadata.google.internal/computeMetadata/v1/project/project-id",
                headers={"Metadata-Flavor": "Google"},
                timeout=1.0,
            )
            if resp.status_code == 200 and resp.text.strip():
                _CACHED_PROJECT_ID = resp.text.strip()
                return _CACHED_PROJECT_ID
        except Exception:
            pass

    # Step 3: Local CLI fallback via gcloud config
    try:
        is_win = sys.platform == "win32"
        res = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
            shell=is_win,
        )
        cli_project = res.stdout.strip()
        if cli_project and cli_project != "(unset)":
            _CACHED_PROJECT_ID = cli_project
            return _CACHED_PROJECT_ID
    except Exception:
        pass

    return None


def resolve_cloud_secret(secret_id: str, project_id: str | None = None) -> str | None:
    """
    Resolves a secret version from Google Cloud Secret Manager.

    Uses a dual-mode strategy:
        - In-memory cache for process lifetime.
        - On Cloud Run: Uses Python SecretManagerServiceClient with container IAM credentials.
        - On Local PCs: Uses `gcloud secrets versions access` CLI using user credentials,
          falling back to Python SDK.

    Args:
        secret_id: Name of the secret (e.g. 'gemini-api-key', 'gmail-agent-token').
        project_id: Optional target GCP Project ID. Resolved automatically if None.

    Returns:
        The decrypted payload string, or None if the secret is unavailable.
    """
    if not secret_id:
        return None

    if secret_id in _CACHED_SECRETS:
        return _CACHED_SECRETS[secret_id]

    target_project = project_id or get_project_id()
    if not target_project:
        return None

    is_cloud = os.getenv("K_SERVICE") is not None

    def _try_sdk() -> str | None:
        try:
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{target_project}/secrets/{secret_id}/versions/latest"
            response = client.access_secret_version(request={"name": name}, timeout=5.0)
            val = response.payload.data.decode("utf-8").strip()
            if val:
                _CACHED_SECRETS[secret_id] = val
                return val
        except Exception:
            pass
        return None

    def _try_cli() -> str | None:
        try:
            is_win = sys.platform == "win32"
            cmd = [
                "gcloud",
                "secrets",
                "versions",
                "access",
                "latest",
                f"--secret={secret_id}",
                f"--project={target_project}",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15, shell=is_win)
            val = res.stdout.strip()
            if val:
                _CACHED_SECRETS[secret_id] = val
                return val
        except Exception:
            pass
        return None

    # Environment-sensitive resolution order
    if is_cloud:
        val = _try_sdk()
        if val is not None:
            return val
        return _try_cli()
    else:
        val = _try_cli()
        if val is not None:
            return val
        return _try_sdk()


def get_gemini_api_key(override: str | None = None) -> str | None:
    """
    Returns the effective Gemini AI API key.

    Resolution Priority:
        1. Explicit function override.
        2. `GEMINI_API_KEY` environment variable.
        3. Google Cloud Secret Manager secrets: 'gemini-api-key' or 'GEMINI_API_KEY'.

    Args:
        override: Optional explicit API key string.

    Returns:
        The resolved API key string, or None if unavailable.
    """
    if override and str(override).strip():
        return str(override).strip()

    env_key = os.getenv("GEMINI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    # Secret Manager resolution fallback
    project_id = get_project_id()
    if project_id:
        secret_val = resolve_cloud_secret("gemini-api-key", project_id)
        if secret_val:
            return secret_val
        secret_val = resolve_cloud_secret("GEMINI_API_KEY", project_id)
        if secret_val:
            return secret_val

    return None


# ==============================================================================
# SECTION 4: Google Cloud Storage (GCS) Configuration
# ==============================================================================

def get_gcs_bucket_name() -> str:
    """
    Returns the canonical GCS bucket name for gmail-agent state and audit logs.

    Resolution Priority:
        1. `GCS_BUCKET_NAME` environment variable.
        2. Canonical convention: `<GCP_PROJECT_ID>-gmail-agent-data`.

    Returns:
        The target GCS bucket name string.
    """
    env_bucket = os.getenv("GCS_BUCKET_NAME")
    if env_bucket and env_bucket.strip():
        return env_bucket.strip()
    project_id = get_project_id() or "default"
    return f"{project_id}-gmail-agent-data"


def get_gcs_state_blob_path() -> str:
    """
    Returns blob path for state file in GCS.

    Returns:
        Relative blob path string (defaults to 'gmail-agent/state.json').
    """
    return os.getenv("GCS_BLOB_PATH", "gmail-agent/state.json")


def get_gcs_log_blob_path() -> str:
    """
    Returns blob path for operational execution audit log in GCS.

    Returns:
        Relative blob path string (defaults to 'gmail-agent/run_log.json').
    """
    return os.getenv("GCS_LOG_BLOB_PATH", "gmail-agent/run_log.json")
