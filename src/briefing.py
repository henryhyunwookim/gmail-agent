"""Compose concise, user-facing email briefings."""
from __future__ import annotations

from typing import Any


def compose_briefing(
    content: dict[str, Any],
    analysis: dict[str, Any],
    include_translation: bool = False,
) -> str:
    """Format analysis results as a concise plain-text email prefix."""
    lines: list[str] = []
    subject = content.get("subject", "")
    sender = content.get("sender", "")
    if subject:
        lines.append(f"Subject: {subject}")
    if sender:
        lines.append(f"From: {sender}")

    summary = analysis.get("executive_summary") or analysis.get("summary", "No summary provided.")
    insights = analysis.get("key_insights") or []
    if not insights and analysis.get("sections"):
        insights = [
            {"topic": item.get("topic", "Insight"), "details": item.get("insight", "")}
            for item in analysis["sections"]
        ]

    lines.extend(["", "💡 Summary & insights", str(summary).strip()])
    for insight in insights:
        topic = insight.get("topic", "")
        details = insight.get("details", "")
        if details:
            label = f"{topic}: " if topic else ""
            lines.append(f"- {label}{details.strip()}")

    highlights = analysis.get("external_source_highlights")
    if highlights and isinstance(highlights, str) and highlights.strip().lower() != "null":
        lines.extend(["", "🌐 External source findings", highlights.strip()])

    takeaways = analysis.get("actionable_takeaways") or []
    if takeaways:
        lines.extend(["", "⚡ Takeaways"])
        lines.extend(f"- {takeaway.strip()}" for takeaway in takeaways if takeaway.strip())

    learning_segments = analysis.get("learning_segments") or []
    if include_translation and learning_segments:
        lines.extend(["", "📚 Chinese study"])
        for index, segment in enumerate(learning_segments[:5], 1):
            lines.append(f"{index}. {segment.get('original', '')}")
            lines.append(f"   Pinyin: {segment.get('pinyin', '')}")
            lines.append(f"   Translation: {segment.get('translation', '')}")
            vocabulary = segment.get("vocabulary") or []
            if vocabulary:
                words = "; ".join(
                    f"{item.get('word', '')} ({item.get('pinyin', '')}) - {item.get('english', '')}"
                    for item in vocabulary
                )
                lines.append(f"   Vocabulary: {words}")

    action_required = bool(analysis.get("action_required"))
    action_status = "Yes" if action_required else "No"
    action_reason = analysis.get("reason", "No action needed.")
    lines.extend(["", f"🎯 Action required: {action_status}", f"Reason: {action_reason}"])

    source_lines = []
    for source in analysis.get("external_sources", []):
        title = source.get("title", "")
        url = source.get("url", "")
        source_type = source.get("type", "link").upper()
        source_lines.append(f"- [{source_type}] {title}: {url}" if title else f"- [{source_type}] {url}")
    unsubscribe_link = analysis.get("unsubscribe_link")
    if unsubscribe_link:
        source_lines.append(f"- Unsubscribe: {unsubscribe_link}")
    if source_lines:
        lines.extend(["", "🔗 Links", *source_lines])

    return "\n".join(lines).strip()