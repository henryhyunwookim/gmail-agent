import os
import sys
from flask import Flask, jsonify
from src.main import main

app = Flask(__name__)

@app.route("/", methods=["POST", "GET"])
def run_agent():
    """Triggers the agent execution."""
    try:
        print("Received trigger request. Starting agent...")
        result = main()
        
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
