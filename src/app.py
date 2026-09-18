import os
import sys
from flask import Flask, jsonify, request
from src.main import main

app = Flask(__name__)

@app.route("/", methods=["POST", "GET"])
def run_agent():
    """Triggers the agent execution."""
    try:
        max_results = None
        # Check query parameters
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

        dry_run = False
        if request.args.get("dry_run"):
            dry_run = request.args.get("dry_run").lower() in ("true", "1", "yes")

        # Check JSON payload if provided
        if request.is_json:
            data = request.get_json(silent=True) or {}
            if max_results is None:
                val = data.get("max_emails") or data.get("max_results")
                if val is not None:
                    try:
                        max_results = int(val)
                    except (ValueError, TypeError):
                        pass
            if not dry_run and "dry_run" in data:
                dry_run = bool(data["dry_run"])

        print(f"Received trigger request. Starting agent (max_results={max_results}, dry_run={dry_run})...")
        result = main(max_results=max_results, dry_run=dry_run)
        
        if result and result.get('success'):
            return jsonify({
                'status': 'success',
                'message': 'Agent run successfully',
                'stats': result.get('stats', {})
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': f"Agent encountered an error: {result.get('error', 'Unknown error')}",
                'stats': result.get('stats', {})
            }), 500
    except Exception as e:
        print(f"Error running agent: {e}")
        return jsonify({
            'status': 'error',
            'message': f"Error: {e}"
        }), 500

if __name__ == "__main__":
    # Cloud Run sets PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
