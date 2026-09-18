import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Any, Dict, Optional

from src.config import (
    get_gcs_bucket_name,
    get_gcs_log_blob_path,
    get_gcs_state_blob_path,
    get_project_id,
)

# Local cache paths default exclusively to OS temp directory to prevent workspace pollution
_LOCAL_STATE_CACHE = os.path.join(tempfile.gettempdir(), "gmail_agent_state_cache.json")
_LOCAL_LOG_CACHE = os.path.join(tempfile.gettempdir(), "gmail_agent_run_log_cache.json")


def _is_cloud_run() -> bool:
    return os.getenv("K_SERVICE") is not None


def _ensure_bucket_exists(client: Any, bucket_name: str, project_id: Optional[str]) -> bool:
    """Helper to check if bucket exists, attempting creation if permitted."""
    try:
        bucket = client.bucket(bucket_name)
        if not bucket.exists():
            print(f"Bucket gs://{bucket_name} not found. Creating...")
            client.create_bucket(bucket, project=project_id)
            print(f"Created bucket gs://{bucket_name}.")
        return True
    except Exception:
        return False


def load_cloud_state(
    bucket_name: Optional[str] = None,
    blob_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Loads state dictionary from Google Cloud Storage with CLI fallback and OS temp cache fallback.
    The Git repository root is NEVER polluted with state files.
    """
    bucket = bucket_name or get_gcs_bucket_name()
    blob = blob_path or get_gcs_state_blob_path()
    is_cloud = _is_cloud_run()

    def _try_sdk() -> Optional[Dict[str, Any]]:
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

    def _try_cli() -> Optional[Dict[str, Any]]:
        try:
            is_win = sys.platform == "win32"
            cmd = ["gcloud", "storage", "cat", f"gs://{bucket}/{blob}"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10, shell=is_win)
            if res.stdout.strip():
                return json.loads(res.stdout)
        except Exception:
            pass
        return None

    # Resolution order based on runtime environment
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
    data: Dict[str, Any],
    bucket_name: Optional[str] = None,
    blob_path: Optional[str] = None,
) -> bool:
    """
    Saves state dictionary directly to GCS and OS temp cache.
    Never writes state to workspace root.
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


def record_run_log(run_summary: Dict[str, Any], bucket_name: Optional[str] = None) -> bool:
    """
    Decoupled operational and audit log persistence.
    1. Streams structured JSON log to stdout for Cloud Run / Cloud Logging ingestion.
    2. Writes operational log to GCS at gs://<bucket>/<service>/run_log.json.
    3. Keeps local fallback strictly in OS temp directory.
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

    # 2. Safe OS temp fallback
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
