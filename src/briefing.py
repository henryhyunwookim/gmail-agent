"""Render concise briefings for plain-text and HTML email clients."""
from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlsplit


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _safe_url(value: Any) -> str:
    url = _clean(value)
    if not url or any(char.isspace() or ord(char) < 32 for char in url):
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        return url
    if parsed.scheme.lower() == "mailto" and parsed.path and "@" in parsed.path:
        return url
    return ""


def _briefing_data(
    content: dict[str, Any], analysis: dict[str, Any], include_translation: bool | None
) -> dict[str, Any]:
    insights = analysis.get("key_insights") or [
        {"topic": item.get("topic", ""), "details": item.get("insight", "")}
        for item in analysis.get("sections") or [] if isinstance(item, dict)
    ]
    clean_insights = [
        (_clean(item.get("topic")), _clean(item.get("details")))
        for item in insights if isinstance(item, dict) and _clean(item.get("details"))
    ]
    segments = analysis.get("learning_segments") or []
    show_study = (
        include_translation if include_translation is not None
        else bool(analysis.get("has_language_study") or analysis.get("has_chinese"))
    )
    study = []
    if show_study or segments:
        for segment in segments[:5]:
            if not isinstance(segment, dict):
                continue
            original = _clean(segment.get("original"))
            if not original:
                continue
            vocabulary = []
            for item in segment.get("vocabulary") or []:
                if not isinstance(item, dict):
                    continue
                term = _clean(item.get("word") or item.get("term"))
                pron = _clean(item.get("pronunciation") or item.get("pinyin"))
                meaning = _clean(item.get("english") or item.get("meaning"))
                if term:
                    vocabulary.append(f"{term} ({pron}) - {meaning}" if pron else f"{term} - {meaning}")
            study.append({
                "original": original,
                "pronunciation": _clean(segment.get("pronunciation") or segment.get("pinyin") or segment.get("phonetics")),
                "translation": _clean(segment.get("translation")),
                "vocabulary": vocabulary,
            })
    links = []
    for source in analysis.get("external_sources") or []:
        if not isinstance(source, dict):
            continue
        url = _safe_url(source.get("url"))
        if url:
            links.append((_clean(source.get("title")) or _clean(source.get("type")) or "Source", url))
    unsubscribe = _safe_url(analysis.get("unsubscribe_link"))
    if unsubscribe:
        links.append(("Unsubscribe", unsubscribe))
    highlights = _clean(analysis.get("external_source_highlights"))
    return {
        "subject": _clean(content.get("subject")),
        "sender": _clean(content.get("sender")),
        "summary": _clean(analysis.get("executive_summary") or analysis.get("summary")) or "No summary provided.",
        "insights": clean_insights,
        "highlights": "" if highlights.lower() == "null" else highlights,
        "takeaways": [_clean(item) for item in analysis.get("actionable_takeaways") or [] if _clean(item)],
        "study": study,
        "language": _clean(analysis.get("target_language")),
        "action_required": bool(analysis.get("action_required")),
        "reason": _clean(analysis.get("reason")) or "No action needed.",
        "links": links,
    }


def compose_briefing(
    content: dict[str, Any], analysis: dict[str, Any], include_translation: bool | None = None
) -> str:
    """Format the analysis as a plain-text email and dry-run preview."""
    data = _briefing_data(content, analysis, include_translation)
    lines = []
    if data["subject"]:
        lines.append(f"Subject: {data['subject']}")
    if data["sender"]:
        lines.append(f"From: {data['sender']}")
    lines.extend(["", "Summary", data["summary"]])
    if data["insights"]:
        lines.extend(["", "Key insights"])
        lines.extend(f"- {topic}: {details}" if topic else f"- {details}" for topic, details in data["insights"])
    if data["highlights"]:
        lines.extend(["", "External source findings", data["highlights"]])
    if data["takeaways"]:
        heading = "Takeaways" if data["action_required"] else "Things to watch"
        lines.extend(["", heading, *(f"- {item}" for item in data["takeaways"])])
    if data["study"]:
        heading = f"Language study ({data['language']})" if data["language"] else "Language study"
        lines.extend(["", heading])
        for index, segment in enumerate(data["study"], 1):
            lines.append(f"{index}. {segment['original']}")
            for label, value in (("Pronunciation", segment["pronunciation"]), ("Translation", segment["translation"])):
                if value:
                    lines.append(f"   {label}: {value}")
            if segment["vocabulary"]:
                lines.append(f"   Vocabulary: {'; '.join(segment['vocabulary'])}")
    lines.extend(["", "Action required", "Yes" if data["action_required"] else "No", f"Reason: {data['reason']}"])
    if data["links"]:
        lines.extend(["", "Links", *(f"- {label}: {url}" for label, url in data["links"])])
    return "\n".join(lines).strip()


def compose_briefing_html(
    content: dict[str, Any], analysis: dict[str, Any], include_translation: bool | None = None
) -> str:
    """Format the same analysis as a restrained, email-compatible HTML document."""
    data = _briefing_data(content, analysis, include_translation)
    sections = []

    def section(title: str, body: str) -> None:
        border_style = 'border-top:1px solid #e5e7eb;padding:20px 0 2px' if sections else 'padding:0 0 2px'
        sections.append(
            f'<section style="{border_style}">'
            f'<h2 style="font-size:16px;line-height:1.4;margin:0 0 10px;color:#1f2937">{escape(title)}</h2>'
            f'{body}</section>'
        )

    def paragraph(value: str) -> str:
        return f'<p style="margin:0 0 12px;white-space:pre-wrap">{escape(value)}</p>'

    def bullets(items: list[str]) -> str:
        return '<ul style="margin:0 0 12px;padding-left:22px">' + ''.join(
            f'<li style="margin:0 0 10px">{escape(item)}</li>' for item in items
        ) + '</ul>'

    section("Summary", paragraph(data["summary"]))
    if data["insights"]:
        insight_items = ''.join(
            '<li style="margin:0 0 14px">'
            + (f'<strong style="color:#1f2937">{escape(topic)}</strong><br>' if topic else '')
            + escape(details) + '</li>'
            for topic, details in data["insights"]
        )
        section("Key insights", '<ul style="margin:0 0 12px;padding-left:22px">' + insight_items + '</ul>')
    if data["highlights"]:
        section("External source findings", paragraph(data["highlights"]))
    if data["takeaways"]:
        heading = "Takeaways" if data["action_required"] else "Things to watch"
        section(heading, bullets(data["takeaways"]))
    if data["study"]:
        items = []
        for segment in data["study"]:
            parts = [f'<strong>{escape(segment["original"])}</strong>']
            for label, value in (("Pronunciation", segment["pronunciation"]), ("Translation", segment["translation"])):
                if value:
                    parts.append(f'<br>{label}: {escape(value)}')
            if segment["vocabulary"]:
                parts.append(f'<br>Vocabulary: {escape("; ".join(segment["vocabulary"]))}')
            items.append(''.join(parts))
        heading = f"Language study ({data['language']})" if data["language"] else "Language study"
        section(heading, '<ol style="margin:0 0 12px;padding-left:22px">' + ''.join(
            f'<li style="margin:0 0 12px">{item}</li>' for item in items
        ) + '</ol>')
    status = "Yes" if data["action_required"] else "No"
    section("Action required", paragraph(status) + paragraph(f"Reason: {data['reason']}"))
    if data["links"]:
        section("Links", '<ul style="margin:0 0 12px;padding-left:22px">' + ''.join(
            f'<li style="margin:0 0 8px"><a href="{escape(url, quote=True)}" style="color:#315b7c">{escape(label)}</a></li>'
            for label, url in data["links"]
        ) + '</ul>')
    return (
        '<!doctype html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;padding:24px 12px;background:#f8fafc;color:#374151;'
        'font:15px/1.6 Arial,Helvetica,sans-serif">'
        '<div style="max-width:640px;margin:0 auto;padding:24px;background:#fff;'
        'border:1px solid #e5e7eb;border-radius:8px">'
        + ''.join(sections) + '</div></body></html>'
    )
