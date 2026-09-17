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

