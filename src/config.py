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


# ==============================================================================
# SECTION 3: GCP Project & Cloud Secret Manager Resolution
# ==============================================================================

def get_project_id() -> str | None:
    """
    Resolves the Google Cloud project ID across local and cloud environments.

    Resolution Cascade:
        1. Environment variables: `GCP_PROJECT_ID` or `GOOGLE_CLOUD_PROJECT`.
        2. Cloud Run / Compute Engine internal metadata server.
        3. Local gcloud CLI active configuration (`gcloud config get-value project`).

    Returns:
        The resolved project ID string, or None if undetermined.
    """
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id:
        return project_id.strip()

    # Step 2: Cloud Run / Compute Engine metadata server resolution
    try:
        import requests
        resp = requests.get(
            "http://metadata.google.internal/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"},
            timeout=1,
        )
        if resp.status_code == 200 and resp.text.strip():
            return resp.text.strip()
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
            timeout=5,
            shell=is_win,
        )
        cli_project = res.stdout.strip()
        if cli_project and cli_project != "(unset)":
            return cli_project
    except Exception:
        pass

    return None


def resolve_cloud_secret(secret_id: str, project_id: str | None = None) -> str | None:
    """
    Resolves a secret version from Google Cloud Secret Manager.

    Uses a dual-mode strategy:
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

    target_project = project_id or get_project_id()
    if not target_project:
        return None

    is_cloud = os.getenv("K_SERVICE") is not None

    def _try_sdk() -> str | None:
        try:
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{target_project}/secrets/{secret_id}/versions/latest"
            response = client.access_secret_version(request={"name": name}, timeout=4.0)
            return response.payload.data.decode("utf-8").strip()
        except Exception:
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
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=8, shell=is_win)
            return res.stdout.strip()
        except Exception:
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
