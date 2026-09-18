"""
Cloud Storage & Decoupled Audit Logging (`src.storage`)
======================================================

Purpose:
    Provides resilient, dual-mode persistence for agent operational state and
    audit logs to Google Cloud Storage (GCS) and Google Cloud Logging without
    polluting the local workspace root or Git repository.

Zero-Workspace-Pollution Guarantee:
    All local caches and fallbacks are strictly confined to the operating system's
    designated temporary directory (`tempfile.gettempdir()`). No state, cache, or
    ephemeral log files are ever written to the Git workspace.

Dual-Mode Architecture:
    - On Google Cloud Run: Uses Python `google.cloud.storage` SDK with the container's
      Service Account credentials.
    - On Local Workstations: Attempts gcloud CLI first (`gcloud storage`), falling back
      to the Python SDK and local OS temp cache.
    - Structured stdout logs (`[AUDIT_LOG]`) are automatically ingested by Google Cloud
      Logging when running on Cloud Run.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Any, Optional

from src.config import (
    get_gcs_bucket_name,
    get_gcs_log_blob_path,
    get_gcs_state_blob_path,
    get_project_id,
)

# ==============================================================================
# SECTION 1: Local Cache Constants & Environment Check
# ==============================================================================

# OS temporary cache paths strictly outside the workspace to prevent repository clutter
_LOCAL_STATE_CACHE: str = os.path.join(tempfile.gettempdir(), "gmail_agent_state_cache.json")
_LOCAL_LOG_CACHE: str = os.path.join(tempfile.gettempdir(), "gmail_agent_run_log_cache.json")


def _is_cloud_run() -> bool:
    """
    Checks if the current process is executing within Google Cloud Run.

    Returns:
        True if K_SERVICE is populated in the environment.
    """
    return os.getenv("K_SERVICE") is not None


# ==============================================================================
# SECTION 2: GCS Bucket Lifecycle Management
# ==============================================================================

def _ensure_bucket_exists(client: Any, bucket_name: str, project_id: str | None) -> bool:
    """
    Verifies GCS bucket existence and attempts creation if it does not yet exist.

    Args:
        client: Google Cloud Storage Client instance.
        bucket_name: Canonical GCS bucket name.
        project_id: Target GCP Project ID.

    Returns:
        True if the bucket exists or was created, False on failure.
    """
    try:
        bucket = client.bucket(bucket_name)
        if not bucket.exists():
            print(f"Bucket gs://{bucket_name} not found. Creating...")
            client.create_bucket(bucket, project=project_id)
            print(f"Created bucket gs://{bucket_name}.")
        return True
    except Exception:
        return False


# ==============================================================================
# SECTION 3: Persistent State Operations
# ==============================================================================

def load_cloud_state(
    bucket_name: str | None = None,
    blob_path: str | None = None,
) -> dict[str, Any]:
    """
    Loads state dictionary from Google Cloud Storage with CLI and OS temp cache fallback.

    Resolution Strategy:
        1. Attempt GCS download via Python SDK or gcloud storage CLI.
        2. Fall back to local OS temporary cache (`_LOCAL_STATE_CACHE`).
        3. Return empty dictionary `{}` if no state has been created yet.

    Args:
        bucket_name: Optional custom bucket name (defaults to canonical project bucket).
        blob_path: Optional custom blob path (defaults to 'gmail-agent/state.json').

    Returns:
        Dictionary representing the loaded state.
    """
    bucket = bucket_name or get_gcs_bucket_name()
    blob = blob_path or get_gcs_state_blob_path()
    is_cloud = _is_cloud_run()

    def _try_sdk() -> dict[str, Any] | None:
        try:
            from google.cloud import storage

            client = storage.Client()
            b = client.bucket(bucket)
            if b.exists():
                bl = b.blob(blob)
                if bl.exists():
                    content = bl.download_as_text(encoding="utf-8")
                    return json.loads(content)
        except Exception:
            pass
        return None

    def _try_cli() -> dict[str, Any] | None:
        try:
            is_win = sys.platform == "win32"
            cmd = ["gcloud", "storage", "cat", f"gs://{bucket}/{blob}"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10, shell=is_win)
            if res.stdout.strip():
                return json.loads(res.stdout)
        except Exception:
            pass
        return None

    # Resolution order based on execution environment
    if is_cloud:
        res = _try_sdk() or _try_cli()
    else:
        res = _try_cli() or _try_sdk()

    if res is not None:
        return res

    # Local OS temp cache fallback
    if os.path.exists(_LOCAL_STATE_CACHE):
        try:
            with open(_LOCAL_STATE_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {}


def save_cloud_state(
    data: dict[str, Any],
    bucket_name: str | None = None,
    blob_path: str | None = None,
) -> bool:
    """
    Saves state dictionary directly to Google Cloud Storage and OS temp cache.

    Guarantees:
        - Never writes to the local Git workspace or project root.
        - Preserves state across multi-PC migrations and Cloud Run invocations.

    Args:
        data: State dictionary to persist.
        bucket_name: Optional custom GCS bucket name.
        blob_path: Optional custom blob path.

    Returns:
        True if state was persisted to GCS, False if saved only to local temp cache.
    """
    bucket = bucket_name or get_gcs_bucket_name()
    blob = blob_path or get_gcs_state_blob_path()
    project_id = get_project_id()
    is_cloud = _is_cloud_run()
    data_str = json.dumps(data, ensure_ascii=False, indent=2)

    # 1. Write to OS temp cache first for safe local fallback
    try:
        with open(_LOCAL_STATE_CACHE, "w", encoding="utf-8") as f:
            f.write(data_str)
    except Exception:
        pass

    def _upload_sdk() -> bool:
        try:
            from google.cloud import storage

            client = storage.Client()
            _ensure_bucket_exists(client, bucket, project_id)
            b = client.bucket(bucket)
            bl = b.blob(blob)
            bl.upload_from_string(data_str, content_type="application/json")
            return True
        except Exception:
            return False

    def _upload_cli() -> bool:
        try:
            is_win = sys.platform == "win32"
            cmd = ["gcloud", "storage", "cp", _LOCAL_STATE_CACHE, f"gs://{bucket}/{blob}"]
            subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15, shell=is_win)
            return True
        except Exception:
            return False

    if is_cloud:
        return _upload_sdk() or _upload_cli()
    else:
        return _upload_cli() or _upload_sdk()


# ==============================================================================
# SECTION 4: Operational Audit & Execution Logging
# ==============================================================================

def record_run_log(run_summary: dict[str, Any], bucket_name: str | None = None) -> bool:
    """
    Decoupled operational and audit log persistence.

    Dual-Channel Ingestion:
        1. Emits structured JSON log to stdout (`[AUDIT_LOG]`) for Cloud Logging.
        2. Writes operational audit entry to GCS at `gs://<bucket>/gmail-agent/run_log.json`.
        3. Maintains a local fallback exclusively in the OS temporary directory.

    Args:
        run_summary: Summary dictionary detailing execution timestamp, stats, and errors.
        bucket_name: Optional target GCS bucket name.

    Returns:
        True if log was uploaded to GCS, False if written to temp fallback only.
    """
    bucket = bucket_name or get_gcs_bucket_name()
    blob = get_gcs_log_blob_path()
    project_id = get_project_id()
    is_cloud = _is_cloud_run()

    payload = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": "gmail-agent",
        **run_summary,
    }

    log_str = json.dumps(payload, ensure_ascii=False)

    # 1. Structured log to stdout (auto-collected by GCP Cloud Logging on Cloud Run)
    print(f"[AUDIT_LOG] {log_str}")

    # 2. Safe OS temp fallback (outside Git repository)
    try:
        with open(_LOCAL_LOG_CACHE, "w", encoding="utf-8") as f:
            f.write(log_str)
    except Exception:
        pass

    def _upload_sdk() -> bool:
        try:
            from google.cloud import storage

            client = storage.Client()
            _ensure_bucket_exists(client, bucket, project_id)
            b = client.bucket(bucket)
            bl = b.blob(blob)
            bl.upload_from_string(log_str, content_type="application/json")
            return True
        except Exception:
            return False

    def _upload_cli() -> bool:
        try:
            is_win = sys.platform == "win32"
            cmd = ["gcloud", "storage", "cp", _LOCAL_LOG_CACHE, f"gs://{bucket}/{blob}"]
            subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15, shell=is_win)
            return True
        except Exception:
            return False

    if is_cloud:
        return _upload_sdk() or _upload_cli()
    else:
        return _upload_cli() or _upload_sdk()
