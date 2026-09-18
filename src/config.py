import os
from typing import Optional
from dotenv import load_dotenv

# Automatically load environment variables from .env
load_dotenv()

# Single Source of Truth for system defaults
DEFAULT_MAX_EMAILS = 20
DEFAULT_SCHEDULE = "0 5,17 * * *"
DEFAULT_TIMEZONE = "Asia/Seoul"

def get_max_emails(override: Optional[int] = None) -> int:
    """
    Returns the effective maximum email batch limit.
    Resolution priority:
      1. Explicit function/CLI override (if provided and valid)
      2. MAX_EMAILS environment variable (from .env or cloud runtime)
      3. DEFAULT_MAX_EMAILS (single source of truth: 20)
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

def get_schedule(override: Optional[str] = None) -> str:
    """
    Returns the effective cron schedule expression.
    Resolution priority:
      1. Explicit override (if provided)
      2. SCHEDULE environment variable (from .env or deployment)
      3. DEFAULT_SCHEDULE (single source of truth: '0 5,17 * * *')
    """
    if override and str(override).strip():
        return str(override).strip()
    env_val = os.getenv("SCHEDULE")
    if env_val and env_val.strip():
        return env_val.strip()
    return DEFAULT_SCHEDULE

def get_timezone(override: Optional[str] = None) -> str:
    """
    Returns the effective timezone.
    Resolution priority:
      1. Explicit override (if provided)
      2. TIMEZONE environment variable (from .env or deployment)
      3. DEFAULT_TIMEZONE (single source of truth: 'Asia/Seoul')
    """
    if override and str(override).strip():
        return str(override).strip()
    env_val = os.getenv("TIMEZONE")
    if env_val and env_val.strip():
        return env_val.strip()
    return DEFAULT_TIMEZONE

def get_interval_minutes(override: Optional[int] = None) -> Optional[int]:
    """
    Returns optional interval in minutes for continuous local execution loop.
    Resolution priority:
      1. Explicit override (if provided)
      2. RUN_INTERVAL_MINUTES environment variable
      3. None (single run)
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


def get_project_id() -> Optional[str]:
    """Get the GCP project ID from environment, gcloud config, or metadata server."""
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id:
        return project_id.strip()

    # Cloud Run / Compute metadata server fallback
    try:
        import requests
        resp = requests.get(
            "http://metadata.google.internal/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"},
            timeout=1
        )
        if resp.status_code == 200 and resp.text.strip():
            return resp.text.strip()
    except Exception:
        pass

    # Local CLI fallback (gcloud config get-value project)
    try:
        import subprocess
        import sys
        is_win = sys.platform == "win32"
        res = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
            shell=is_win
        )
        cli_project = res.stdout.strip()
        if cli_project and cli_project != "(unset)":
            return cli_project
    except Exception:
        pass

    return None


def resolve_cloud_secret(secret_id: str, project_id: Optional[str] = None) -> Optional[str]:
    """Resolves a secret from GCP Secret Manager via SDK and gcloud CLI fallback."""
    if not secret_id:
        return None

    target_project = project_id or get_project_id()
    if not target_project:
        return None

    is_cloud = os.getenv("K_SERVICE") is not None

    def _try_sdk() -> Optional[str]:
        try:
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{target_project}/secrets/{secret_id}/versions/latest"
            response = client.access_secret_version(request={"name": name}, timeout=4.0)
            return response.payload.data.decode("utf-8").strip()
        except Exception:
            return None

    def _try_cli() -> Optional[str]:
        try:
            import subprocess
            import sys
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

    if is_cloud:
        # On Cloud Run: SDK with container service account credentials
        val = _try_sdk()
        if val is not None:
            return val
        return _try_cli()
    else:
        # On local PCs: gcloud CLI uses authenticated user credentials directly
        val = _try_cli()
        if val is not None:
            return val
        return _try_sdk()


def get_gemini_api_key(override: Optional[str] = None) -> Optional[str]:
    """
    Returns effective Gemini API Key.
    Resolution priority:
      1. Explicit override
      2. GEMINI_API_KEY environment variable (from .env or cloud runtime)
      3. Google Cloud Secret Manager (secrets 'gemini-api-key' or 'GEMINI_API_KEY')
    """
    if override and str(override).strip():
        return str(override).strip()

    env_key = os.getenv("GEMINI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    # Secret Manager resolution
    project_id = get_project_id()
    if project_id:
        secret_val = resolve_cloud_secret("gemini-api-key", project_id)
        if secret_val:
            return secret_val
        secret_val = resolve_cloud_secret("GEMINI_API_KEY", project_id)
        if secret_val:
            return secret_val

    return None


def get_gcs_bucket_name() -> str:
    """Returns the canonical GCS bucket name for gmail-agent state and logs."""
    env_bucket = os.getenv("GCS_BUCKET_NAME")
    if env_bucket and env_bucket.strip():
        return env_bucket.strip()
    project_id = get_project_id() or "default"
    return f"{project_id}-gmail-agent-data"


def get_gcs_state_blob_path() -> str:
    """Returns blob path for state file in GCS."""
    return os.getenv("GCS_BLOB_PATH", "gmail-agent/state.json")


def get_gcs_log_blob_path() -> str:
    """Returns blob path for operational execution log in GCS."""
    return os.getenv("GCS_LOG_BLOB_PATH", "gmail-agent/run_log.json")

