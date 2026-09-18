"""
Cloud Run HTTP Webhook & Flask Application (`src.app`)
======================================================

Purpose:
    Exposes an HTTP server for Google Cloud Run, serving as the entrypoint
    invoked by Google Cloud Scheduler via OIDC-authenticated HTTP POST/GET requests.

HTTP Contract & Parameters:
    - Route: `/` (supports POST and GET)
    - Query Parameters:
        - `max_emails` / `max_results` (int, optional): Override the unread batch size.
        - `dry_run` (bool, optional): If 'true', simulates summarization without forwarding.
    - JSON Body (Optional for POST requests):
        - `{"max_emails": 15, "dry_run": false}`

Response Schema:
    - HTTP 200 OK on successful agent run:
        `{"status": "success", "message": "Agent run successfully", "stats": {...}}`
    - HTTP 500 Internal Server Error on processing exception:
        `{"status": "error", "message": "Agent encountered an error: ...", "stats": {...}}`
"""
from __future__ import annotations

import os
import sys
from typing import Any

from flask import Flask, Response, jsonify, request

from src.main import main


# ==============================================================================
# SECTION 1: Flask Application Initialization
# ==============================================================================

app: Flask = Flask(__name__)


# ==============================================================================
# SECTION 2: Cloud Run Trigger Endpoint
# ==============================================================================

@app.route("/", methods=["POST", "GET"])
def run_agent() -> tuple[Response, int]:
    """
    HTTP endpoint triggered by Cloud Scheduler or manual webhook invocation.

    Returns:
        Tuple of (Flask JSON response, HTTP status code).
    """
    try:
        max_results: int | None = None

        # Step 1: Parse query parameters
        if request.args.get("max_emails"):
            try:
                max_results = int(request.args.get("max_emails"))
            except ValueError:
                pass
        elif request.args.get("max_results"):
            try:
                max_results = int(request.args.get("max_results"))
            except ValueError:
                pass

        dry_run: bool = False
        if request.args.get("dry_run"):
            dry_run = request.args.get("dry_run", "").lower() in ("true", "1", "yes")

        # Step 2: Parse JSON payload if provided in request body
        if request.is_json:
            data: dict[str, Any] = request.get_json(silent=True) or {}
            if max_results is None:
                val = data.get("max_emails") or data.get("max_results")
                if val is not None:
                    try:
                        max_results = int(val)
                    except (ValueError, TypeError):
                        pass
            if not dry_run and "dry_run" in data:
                dry_run = bool(data["dry_run"])

        print(f"[APP] Received trigger request. Starting agent (max_results={max_results}, dry_run={dry_run})...")

        # Step 3: Execute the main agent pipeline
        result = main(max_results=max_results, dry_run=dry_run)

        # Step 4: Construct HTTP response
        if result and result.get("success"):
            return (
                jsonify({
                    "status": "success",
                    "message": "Agent run successfully",
                    "stats": result.get("stats", {}),
                }),
                200,
            )
        else:
            return (
                jsonify({
                    "status": "error",
                    "message": f"Agent encountered an error: {result.get('error', 'Unknown error')}",
                    "stats": result.get("stats", {}),
                }),
                500,
            )
    except Exception as e:
        print(f"[APP] Unhandled exception in run_agent: {e}")
        return (
            jsonify({
                "status": "error",
                "message": f"Error: {e}",
            }),
            500,
        )


# ==============================================================================
# SECTION 3: Local Dev Server Entry Point
# ==============================================================================

if __name__ == "__main__":
    # Google Cloud Run injects the PORT environment variable (defaults to 8080)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
