"""
Self-Improving Agent Memory & Reflection Engine (`src.agent_memory`)
===================================================================

Purpose:
    Manages cumulative memory, feedback harvesting from user Gmail actions
    (stars, label adjustments, read states), and autonomous prompt reflection
    to allow the Gmail Agent to self-improve over time without manual tuning.

Memory Architecture:
    1. Persistent Storage in Google Cloud Storage:
       `gs://<GCS_BUCKET_NAME>/gmail-agent/agent_memory.json`
    2. Zero-Workspace-Pollution Cache:
       Local fallback confined strictly to OS temporary directory
       (`tempfile.gettempdir()/gmail_agent_memory_cache.json`).
    3. Learned Sender Insights & Operational Rules:
       Stores synthesized domain rules, sender patterns, and interaction histories.
    4. Reflexion / Meta-Review:
       Analyzes recent execution decisions against user signals (starred messages,
       relabeling) to distill concise, high-value prompt hints.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Optional

import google.generativeai as genai

from src.config import (
    get_gcs_bucket_name,
    get_project_id,
)

# OS temporary cache path strictly outside workspace to prevent git pollution
_LOCAL_MEMORY_CACHE: str = os.path.join(tempfile.gettempdir(), "gmail_agent_memory_cache.json")
_GCS_MEMORY_BLOB: str = os.getenv("GCS_AGENT_MEMORY_BLOB", "gmail-agent/agent_memory.json")

# In-memory runtime cache
_CACHED_AGENT_MEMORY: dict[str, Any] | None = None


def _get_default_memory() -> dict[str, Any]:
    """Returns baseline agent memory structure."""
    return {
        "version": 1,
        "last_reflected_at": None,
        "learned_hints": [
            "Prioritize system design, technical trade-offs, and architecture over marketing announcements.",
            "Label routine e-commerce order and shipping confirmations as Receipts and skip forwarding.",
            "Informational status alerts or routine git notifications do not require action unless explicitly addressed to recipient.",
        ],
        "sender_insights": {},
        "recent_interactions": [],
        "user_signals": {
            "starred_senders": [],
            "deprioritized_senders": [],
        },
    }


class AgentMemoryManager:
    """
    Manages persistent memory, feedback harvesting, and prompt reflection.
    """

    def __init__(
        self,
        bucket_name: str | None = None,
        blob_path: str = _GCS_MEMORY_BLOB,
        local_cache_path: str = _LOCAL_MEMORY_CACHE,
    ) -> None:
        self.bucket_name: str = bucket_name or get_gcs_bucket_name()
        self.blob_path: str = blob_path
        self.local_cache_path: str = local_cache_path
        self._gcs_client: Any = None

    def _get_gcs_client(self) -> Any:
        if self._gcs_client is None:
            try:
                from google.cloud import storage
                self._gcs_client = storage.Client()
            except Exception:
                self._gcs_client = None
        return self._gcs_client

    def load_memory(self) -> dict[str, Any]:
        """
        Loads agent memory from GCS with gcloud CLI and local temp cache fallback.
        """
        global _CACHED_AGENT_MEMORY
        if _CACHED_AGENT_MEMORY is not None:
            return _CACHED_AGENT_MEMORY

        # 1. Try Google Cloud Storage Python Client
        client = self._get_gcs_client()
        if client and self.bucket_name:
            try:
                bucket = client.bucket(self.bucket_name)
                blob = bucket.blob(self.blob_path)
                if blob.exists():
                    data = blob.download_as_text(encoding="utf-8")
                    parsed = json.loads(data)
                    print(f"[MEMORY] Loaded agent memory from GCS gs://{self.bucket_name}/{self.blob_path}")
                    _CACHED_AGENT_MEMORY = self._validate_defaults(parsed)
                    return _CACHED_AGENT_MEMORY
            except Exception:
                pass

        # 2. Try gcloud CLI fallback (developer workstations)
        if self.bucket_name:
            try:
                is_win = sys.platform == "win32"
                cmd = ["gcloud", "storage", "cat", f"gs://{self.bucket_name}/{self.blob_path}"]
                res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=8, shell=is_win)
                if res.stdout.strip():
                    parsed = json.loads(res.stdout)
                    print(f"[MEMORY] Loaded agent memory via gcloud storage CLI.")
                    _CACHED_AGENT_MEMORY = self._validate_defaults(parsed)
                    return _CACHED_AGENT_MEMORY
            except Exception:
                pass

        # 3. Try local cache file in OS temp directory
        if os.path.exists(self.local_cache_path):
            try:
                with open(self.local_cache_path, "r", encoding="utf-8") as f:
                    parsed = json.load(f)
                print(f"[MEMORY] Loaded agent memory from local temp cache.")
                _CACHED_AGENT_MEMORY = self._validate_defaults(parsed)
                return _CACHED_AGENT_MEMORY
            except Exception:
                pass

        # 4. Fallback baseline
        default_mem = _get_default_memory()
        self._save_local(default_mem)
        _CACHED_AGENT_MEMORY = default_mem
        return _CACHED_AGENT_MEMORY

    def save_memory(self, memory_data: dict[str, Any]) -> bool:
        """
        Saves updated agent memory to GCS and OS temp cache.
        """
        global _CACHED_AGENT_MEMORY
        _CACHED_AGENT_MEMORY = memory_data
        self._save_local(memory_data)

        if not self.bucket_name:
            return True

        data_str = json.dumps(memory_data, ensure_ascii=False, indent=2)

        # 1. Try Google Cloud Storage Python Client
        client = self._get_gcs_client()
        if client and self.bucket_name:
            try:
                bucket = client.bucket(self.bucket_name)
                blob = bucket.blob(self.blob_path)
                blob.upload_from_string(data_str, content_type="application/json")
                print(f"[MEMORY] Successfully saved agent memory to gs://{self.bucket_name}/{self.blob_path}")
                return True
            except Exception:
                pass

        # 2. Try gcloud CLI fallback
        if self.bucket_name and os.path.exists(self.local_cache_path):
            try:
                is_win = sys.platform == "win32"
                cmd = ["gcloud", "storage", "cp", self.local_cache_path, f"gs://{self.bucket_name}/{self.blob_path}"]
                subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=12, shell=is_win)
                print(f"[MEMORY] Saved agent memory to GCS via gcloud storage CLI.")
                return True
            except Exception:
                pass

        return False

    def _save_local(self, memory_data: dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.local_cache_path)), exist_ok=True)
            with open(self.local_cache_path, "w", encoding="utf-8") as f:
                json.dump(memory_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _validate_defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        defaults = _get_default_memory()
        for key, val in defaults.items():
            if key not in data:
                data[key] = val
        return data

    # ==========================================================================
    # Dynamic Prompt Formatting
    # ==========================================================================

    def get_formatted_hints(self, limit: int = 10) -> str:
        """
        Renders top learned operational hints into prompt text.
        """
        memory = self.load_memory()
        hints = memory.get("learned_hints", [])[:limit]
        if not hints:
            return ""

        bullet_points = "\n".join(f"- {h}" for h in hints)
        return f"""ACCUMULATED OPERATIONAL GUIDELINES (Learned from past user interactions):
{bullet_points}
"""

    def record_interaction(
        self,
        msg_id: str,
        sender: str,
        subject: str,
        category: str,
        triage_action: str,
        action_required: bool,
    ) -> None:
        """
        Appends an email processing event to recent interaction history for reflection.
        """
        memory = self.load_memory()
        interactions = memory.setdefault("recent_interactions", [])

        # Record entry
        interactions.append({
            "msg_id": msg_id,
            "sender": sender,
            "subject": subject[:120],
            "category": category,
            "triage_action": triage_action,
            "action_required": action_required,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Keep capped at most recent 60 interactions
        if len(interactions) > 60:
            memory["recent_interactions"] = interactions[-60:]

        self.save_memory(memory)

    # ==========================================================================
    # Feedback Signal Harvesting & Reflection
    # ==========================================================================

    def harvest_signals(self, gmail_service: Any) -> int:
        """
        Inspects recent message IDs in Gmail to harvest implicit user feedback:
        - Was the email starred by the user? (High value signal)
        - Was the email trashed or marked spam? (Deprioritized signal)
        - Was ActionRequired removed by user? (Correction signal)

        Returns:
            Count of newly harvested feedback signals.
        """
        memory = self.load_memory()
        recent = memory.get("recent_interactions", [])
        if not recent:
            return 0

        signals = memory.setdefault("user_signals", {"starred_senders": [], "deprioritized_senders": []})
        starred_senders = set(signals.get("starred_senders", []))
        deprioritized_senders = set(signals.get("deprioritized_senders", []))
        harvested_count = 0

        # Sample up to 15 recent messages to inspect current Gmail label states
        sample_messages = recent[-15:]
        for entry in sample_messages:
            msg_id = entry.get("msg_id")
            sender = entry.get("sender", "")
            if not msg_id or not sender:
                continue

            try:
                msg = gmail_service.users().messages().get(
                    userId="me", id=msg_id, format="minimal"
                ).execute()
                label_ids = set(msg.get("labelIds", []))

                # Positive signal: Starred by user
                if "STARRED" in label_ids and sender not in starred_senders:
                    starred_senders.add(sender)
                    harvested_count += 1
                    print(f"[MEMORY] Harvested positive signal (STARRED): {sender}")

                # Negative signal: Trashed or marked as Spam
                if ("TRASH" in label_ids or "SPAM" in label_ids) and sender not in deprioritized_senders:
                    deprioritized_senders.add(sender)
                    harvested_count += 1
                    print(f"[MEMORY] Harvested deprioritization signal (TRASH/SPAM): {sender}")

            except Exception:
                continue

        signals["starred_senders"] = list(starred_senders)[-25:]
        signals["deprioritized_senders"] = list(deprioritized_senders)[-25:]
        if harvested_count > 0:
            self.save_memory(memory)

        return harvested_count

    def reflect_and_optimize(self, api_key: str) -> bool:
        """
        Executes autonomous meta-reflection on accumulated interactions and feedback,
        distilling updated operational rules and pruning stale guidelines.
        """
        memory = self.load_memory()
        interactions = memory.get("recent_interactions", [])
        if len(interactions) < 5:
            # Not enough interaction data to reflect yet
            return False

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.8-flash")

        current_hints = memory.get("learned_hints", [])
        signals = memory.get("user_signals", {})
        recent_samples = interactions[-20:]

        reflection_prompt = f"""You are the meta-reflection engine for an executive AI email assistant.
Your goal is to optimize the assistant's operational guidelines based on real accumulated email data and user feedback.

CURRENT GUIDELINES:
{json.dumps(current_hints, ensure_ascii=False, indent=2)}

USER FEEDBACK SIGNALS:
Starred / High-Value Senders: {signals.get('starred_senders', [])}
Deprioritized / Trashed Senders: {signals.get('deprioritized_senders', [])}

RECENT EMAIL INTERACTIONS & TRIAGE DECISIONS:
{json.dumps(recent_samples, ensure_ascii=False, indent=2)}

TASK:
1. Identify recurring patterns, edge cases, or false positives in categorization and action requirements.
2. Formulate 4 to 8 crisp, authoritative operational rules that will guide the summarizer in future runs.
3. Keep rules concise, concrete, actionable, and non-redundant. Focus on system architecture depth, transactional noise filtering, and accurate action detection.

Respond with ONLY valid JSON:
{{
    "optimized_hints": [
        "Concise rule 1...",
        "Concise rule 2..."
    ],
    "reflection_summary": "1-2 sentences summarizing key behavioral adjustments made"
}}
"""
        try:
            resp = model.generate_content(reflection_prompt)
            text = resp.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = json.loads(text)
            new_hints = result.get("optimized_hints", [])
            summary = result.get("reflection_summary", "")

            if new_hints and isinstance(new_hints, list):
                # Bound hints to top 8 to prevent context bloat
                memory["learned_hints"] = new_hints[:8]
                memory["last_reflected_at"] = datetime.now(timezone.utc).isoformat()
                self.save_memory(memory)
                print(f"[MEMORY] Reflection complete. {summary}")
                return True
        except Exception as e:
            print(f"[MEMORY] Reflection pass failed: {e}")

        return False
