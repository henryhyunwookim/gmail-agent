"""
Convenience Entrypoint: Multi-PC Secret Synchronization Tool
=============================================================

Purpose:
    Provides a quick, root-level CLI shortcut to synchronize local credentials
    (token.json, credentials.json, GEMINI_API_KEY) into Google Cloud Secret Manager.
    Delegates execution directly to `deployment.sync_secrets.main`.

Usage:
    python sync_secrets.py [--project YOUR_PROJECT_ID]

Prerequisites:
    - Google Cloud SDK (`gcloud auth login`) OR valid Application Default Credentials (ADC).
    - Google Cloud Project with Secret Manager API enabled.

Outputs:
    Synchronizes secrets directly to:
      - `gmail-agent-token`
      - `gmail-oauth-credentials`
      - `gemini-api-key`
"""
from __future__ import annotations

import sys
from deployment.sync_secrets import main

if __name__ == "__main__":
    main()
