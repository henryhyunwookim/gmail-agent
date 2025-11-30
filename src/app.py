import os
import sys
from flask import Flask
from src.main import main

app = Flask(__name__)

@app.route("/", methods=["POST", "GET"])
def run_agent():
    """Triggers the agent execution."""
    try:
        print("Received trigger request. Starting agent...")
        # Capture stdout to return in response if needed, or just log it
        main()
        return "Agent run successfully", 200
    except Exception as e:
        print(f"Error running agent: {e}")
        return f"Error: {e}", 500

if __name__ == "__main__":
    # Cloud Run sets PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
