"""Compose concise, user-facing email briefings."""
from __future__ import annotations

from typing import Any


def compose_briefing(
    content: dict[str, Any],
    analysis: dict[str, Any],
    include_translation: bool | None = None,
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
    target_lang = analysis.get("target_language")
    show_study = (
        include_translation
        if include_translation is not None
        else bool(analysis.get("has_language_study") or analysis.get("has_chinese"))
    )
    if (show_study or learning_segments) and learning_segments:
        header = f"📚 Language study ({target_lang})" if target_lang else "📚 Language study"
        lines.extend(["", header])
        for index, segment in enumerate(learning_segments[:5], 1):
            original = segment.get("original", "").strip()
            pron = segment.get("pronunciation") or segment.get("pinyin") or segment.get("phonetics") or ""
            translation = segment.get("translation", "").strip()
            lines.append(f"{index}. {original}")
            if pron:
                lines.append(f"   Pronunciation: {pron.strip()}")
            if translation:
                lines.append(f"   Translation: {translation}")
            vocabulary = segment.get("vocabulary") or []
            if vocabulary:
                vocab_parts = []
                for item in vocabulary:
                    term = item.get("word") or item.get("term") or ""
                    p = item.get("pronunciation") or item.get("pinyin") or ""
                    meaning = item.get("english") or item.get("meaning") or ""
                    if p:
                        vocab_parts.append(f"{term} ({p}) - {meaning}")
                    else:
                        vocab_parts.append(f"{term} - {meaning}")
                lines.append(f"   Vocabulary: {'; '.join(vocab_parts)}")

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