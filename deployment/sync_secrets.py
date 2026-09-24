"""
Multi-PC Cloud Migration: Secret Synchronization Tool
=====================================================

Purpose:
    Synchronizes local Gmail OAuth tokens, Google OAuth client credentials, and
    Gemini API keys into Google Cloud Secret Manager. This allows zero-setup,
    credential-free execution across any PC, laptop, or Cloud Run instance.

Usage / CLI Invocation:
    python deployment/sync_secrets.py [--project YOUR_PROJECT_ID]

Prerequisites & Dependencies:
    - Python 3.10+
    - Google Cloud SDK (`gcloud` CLI installed and authenticated via `gcloud auth login`)
      OR Google Cloud Secret Manager Python client (`google-cloud-secret-manager`).

Inputs & Outputs:
    - Inputs:
        - `token.json` (local Gmail user OAuth token, if present)
        - `credentials.json` (local OAuth client secrets JSON, if present)
        - `GEMINI_API_KEY` (from environment or prompt, if present)
        - `--project` CLI flag or active gcloud project
    - Outputs:
        - Creates / updates secrets in Google Cloud Secret Manager:
            - `gmail-agent-token`
            - `gmail-oauth-credentials`
            - `gemini-api-key`
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from typing import Optional


# ==============================================================================
# SECTION 1: Project Resolution Utilities
# ==============================================================================

def get_default_project_id() -> str | None:
    """
    Resolves the active Google Cloud Project ID.

    Resolution Priority:
        1. Environment variables: `GCP_PROJECT_ID` or `GOOGLE_CLOUD_PROJECT`.
        2. Active gcloud CLI configuration (`gcloud config get-value project`).

    Returns:
        The resolved project ID string, or None if undetermined.
    """
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id and project_id.strip():
        return project_id.strip()

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
        val = res.stdout.strip()
        if val and val != "(unset)":
            return val
    except Exception:
        pass
    return None


# ==============================================================================
# SECTION 2: Secret Manager Synchronization Logic
# ==============================================================================

def sync_secret(secret_name: str, payload_str: str, project_id: str) -> bool:
    """
    Synchronizes a string payload into Google Cloud Secret Manager.

    Uses a robust dual-mode resolution:
        1. Method 1: Google Cloud Secret Manager Python SDK (fast, in-memory).
        2. Method 2: gcloud CLI fallback with automatic creation if secret is missing.

    Args:
        secret_name: Name of the secret in Secret Manager (e.g. 'gmail-agent-token').
        payload_str: String payload to store as the latest secret version.
        project_id: Target Google Cloud Project ID.

    Returns:
        True if the secret version was successfully created, False otherwise.
    """
    if not payload_str or not payload_str.strip():
        print(f"[-] Skipping empty secret: {secret_name}")
        return False

    print(f"[*] Syncing secret '{secret_name}' to project '{project_id}'...")

    # --------------------------------------------------------------------------
    # Method 1: Python SDK (Direct In-Memory API Call)
    # --------------------------------------------------------------------------
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{project_id}"
        secret_path = f"projects/{project_id}/secrets/{secret_name}"

        # Check if secret already exists; if not, create it
        try:
            client.get_secret(request={"name": secret_path})
        except Exception:
            print(f"    Secret '{secret_name}' does not exist. Creating...")
            client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": secret_name,
                    "secret": {"replication": {"automatic": {}}},
                }
            )

        # Add new secret version with payload
        client.add_secret_version(
            request={
                "parent": secret_path,
                "payload": {"data": payload_str.encode("utf-8")},
            }
        )
        print(f"[+] Successfully synced '{secret_name}' via SDK.")
        return True
    except Exception as sdk_err:
        print(f"    SDK sync failed ({sdk_err}), falling back to gcloud CLI...")

    # --------------------------------------------------------------------------
    # Method 2: gcloud CLI Fallback (Uses User Login Credentials)
    # --------------------------------------------------------------------------
    try:
        is_win = sys.platform == "win32"

        # Check if secret exists via CLI
        check_cmd = ["gcloud", "secrets", "describe", secret_name, f"--project={project_id}"]
        check_res = subprocess.run(check_cmd, capture_output=True, text=True, shell=is_win)

        if check_res.returncode != 0:
            print(f"    Creating secret '{secret_name}' via gcloud...")
            create_cmd = [
                "gcloud",
                "secrets",
                "create",
                secret_name,
                "--replication-policy=automatic",
                f"--project={project_id}",
            ]
            subprocess.run(create_cmd, check=True, capture_output=True, text=True, shell=is_win)

        # Write payload to OS temp directory (strictly outside workspace root)
        temp_file = os.path.join(tempfile.gettempdir(), f"sync_secret_{secret_name}.tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(payload_str)

            add_cmd = [
                "gcloud",
                "secrets",
                "versions",
                "add",
                secret_name,
                f"--data-file={temp_file}",
                f"--project={project_id}",
            ]
            subprocess.run(add_cmd, check=True, capture_output=True, text=True, timeout=15, shell=is_win)
            print(f"[+] Successfully synced '{secret_name}' via gcloud CLI.")
            return True
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
    except Exception as cli_err:
        print(f"[!] Error syncing '{secret_name}': {cli_err}")
        return False


# ==============================================================================
# SECTION 3: CLI Entry Point
# ==============================================================================

def main() -> None:
    """
    Parses CLI flags and executes the multi-secret synchronization pipeline.
    """
    parser = argparse.ArgumentParser(
        description="Sync local credentials to Google Cloud Secret Manager for multi-PC portability"
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="GCP Project ID (defaults to active gcloud project or GCP_PROJECT_ID)",
    )
    args = parser.parse_args()

    project_id = args.project or get_default_project_id()
    if not project_id:
        print("[ERROR] Could not determine GCP project ID. Provide --project <ID> or run 'gcloud config set project <ID>'.")
        sys.exit(1)

    print(f"=== Multi-PC Secret Manager Sync (Project: {project_id}) ===")

    synced_count = 0

    # Step 1: token.json -> gmail-agent-token
    token_path = "token.json"
    if os.path.exists(token_path):
        with open(token_path, "r", encoding="utf-8") as f:
            token_content = f.read().strip()
        if sync_secret("gmail-agent-token", token_content, project_id):
            synced_count += 1
    else:
        print("[i] 'token.json' not found locally. Skipping.")

    # Step 2: credentials.json -> gmail-oauth-credentials
    creds_path = "credentials.json"
    if os.path.exists(creds_path):
        with open(creds_path, "r", encoding="utf-8") as f:
            creds_content = f.read().strip()
        if sync_secret("gmail-oauth-credentials", creds_content, project_id):
            synced_count += 1
    else:
        print("[i] 'credentials.json' not found locally. Skipping.")

    # Step 3: GEMINI_API_KEY -> gemini-api-key
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key and gemini_key.strip():
        if sync_secret("gemini-api-key", gemini_key.strip(), project_id):
            synced_count += 1
    else:
        print("[i] 'GEMINI_API_KEY' not found in environment. Skipping.")

    print(f"\nCompleted! {synced_count} secret(s) synchronized to Google Cloud Secret Manager.")


if __name__ == "__main__":
    main()
