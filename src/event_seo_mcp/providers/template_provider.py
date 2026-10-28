"""Deterministic template provider (no external API)."""

from __future__ import annotations

from event_seo_mcp.providers.base import AIProvider
from event_seo_mcp.schemas.content import ContentType, GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord

CONTENT_TEMPLATES: dict[str, tuple[str, str, str]] = {
    "event_directory_description": (
        "{title} — {city}",
        "{description}\n\nWhen: {start} ({timezone})\nWhere: {venue}\nRegister: {registration}\nOrganizer: {organizer}",
        "Register now",
    ),
    "event_calendar_listing": (
        "{title}",
        "{title} takes place on {start} ({timezone}). Audience: {audience}. Details: {landing}",
        "View event details",
    ),
    "partner_promotion_email": (
        "Partnership opportunity: {title}",
        "Hello,\n\nWe are hosting {title} on {start}. Audience: {audience}.\n\n{description}\n\nPartners: {partners}\nLanding page: {landing}\n\nWould you be open to co-promotion?\n\nThanks,\n{organizer}",
        "Reply to discuss partnership",
    ),
    "community_post": (
        "{title}",
        "{title} — {start} ({timezone})\n\n{description}\n\nWho it's for: {audience}\nMore info: {landing}",
        "Learn more",
    ),
    "digital_pr_release": (
        "{organizer} Announces {title}",
        "FOR IMMEDIATE RELEASE\n\n{organizer} today announced {title}, scheduled for {start} ({timezone}).\n\n{description}\n\nApproved claims:\n{claims}\n\nMedia contact: {organizer}\nEvent URL: {landing}",
        "Read the full announcement",
    ),
    "guest_post_pitch": (
        "Pitch: Insights around {keywords} tied to {title}",
        "Hi editors,\n\nI'd like to pitch a practical article related to {keywords}, timed with {title} on {start}.\n\nAngle: lessons for {audience}.\nOutline available on request.\n\nBest,\n{organizer}",
        "Request full outline",
    ),
    "guest_article": (
        "Practical takeaways for {audience} from {title}",
        "Introduction\n{description}\n\nKey themes\n- {keywords}\n\nAgenda highlights\n{agenda}\n\nConclusion\nVisit {landing} for registration and details. Claims are limited to approved statements only.",
        "Register for the event",
    ),
    "linkedin_post": (
        "{title}",
        "{title} is coming up on {start}.\n\nBuilt for {audience}.\n\n{description}\n\nCTA: {landing}",
        "See agenda & register",
    ),
    "speaker_announcement": (
        "Speakers announced for {title}",
        "Excited to share speakers for {title}:\n{speakers}\n\nJoin us on {start}.\n{landing}",
        "Meet the speakers",
    ),
    "customer_success_story": (
        "How teams prepare for {title}",
        "A short success narrative for {title} (approved claims only):\n{claims}\n\nLearn more: {landing}",
        "Read the story",
    ),
    "research_summary": (
        "Research notes: {keywords}",
        "Summary tied to {title} for {audience}.\nKeywords: {keywords}\nApproved claims:\n{claims}\n\nSource event: {landing}",
        "Explore the research themes",
    ),
    "agenda_highlights": (
        "Agenda highlights: {title}",
        "Highlights for {title} on {start}:\n{agenda}\n\nFull details: {landing}",
        "View full agenda",
    ),
    "executive_poll": (
        "Poll for {audience}",
        "Quick poll ahead of {title}: what matters most for {audience} regarding {keywords}?\n\nJoin the conversation and see the event: {landing}",
        "Cast your take / join the event",
    ),
    "partner_spotlight": (
        "Partner spotlight for {title}",
        "Spotlighting partners for {title}: {partners}\n\n{description}\n\n{landing}",
        "Meet our partners",
    ),
}


class TemplateProvider(AIProvider):
    name = "template"

    def available(self) -> bool:
        return True

    def generate_content(
        self,
        event: EventRecord,
        platform: PlatformRecord,
        content_type: ContentType,
        *,
        extra_instructions: str | None = None,
    ) -> GeneratedContent:
        title_t, body_t, cta = CONTENT_TEMPLATES.get(
            content_type,
            CONTENT_TEMPLATES["event_directory_description"],
        )
        values = {
            "title": event.event_title,
            "description": event.event_description.strip(),
            "start": event.start_datetime.isoformat(),
            "timezone": event.timezone,
            "venue": event.venue_name or ("Virtual" if event.virtual_event else "TBA"),
            "city": event.city or "TBA",
            "registration": str(event.registration_url),
            "organizer": event.organizer_name,
            "audience": event.target_audience,
            "landing": str(event.landing_page_url),
            "partners": ", ".join(event.partner_names or []) or "N/A",
            "speakers": "\n".join(f"- {s}" for s in (event.speakers or [])) or "- TBA",
            "agenda": "\n".join(f"- {a}" for a in (event.agenda or [])) or "- TBA",
            "keywords": ", ".join(event.primary_keywords),
            "claims": "\n".join(f"- {c}" for c in (event.approved_claims or ["No additional approved claims."])),
        }
        title = title_t.format(**values)
        body = body_t.format(**values)
        if extra_instructions:
            body = f"{body}\n\nEditor notes: {extra_instructions}"
        source_fields = [
            "event_title",
            "event_description",
            "start_datetime",
            "timezone",
            "landing_page_url",
            "organizer_name",
            "primary_keywords",
        ]
        content = GeneratedContent(
            platform_id=platform.platform_id,
            event_id=event.event_id,
            content_type=content_type,  # type: ignore[arg-type]
            title=title[:500],
            body=body,
            destination_url=str(event.landing_page_url),
            cta=cta,
            suggested_keywords=list(event.primary_keywords),
            character_count=len(body),
            source_event_fields=source_fields,
            validation_status="needs_review",
            approval_status="draft",
        )
        return content
