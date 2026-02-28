import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Dict, List, Optional, Tuple

import nextcord

from ..storage.store import Store, TicketSnapshot, TicketRecord


@dataclass
class BuiltTranscript:
    markdown: str
    html: str
    path: str


class TicketModule:
    def __init__(self, store: Store, transcript_dir: str = "data/transcripts"):
        self.store = store
        self.transcript_dir = transcript_dir

    def is_ticket_channel(self, channel: Optional[nextcord.abc.GuildChannel]) -> bool:
        if channel is None:
            return False
        if self.store.ticket_get_by_channel(channel.id):
            return True
        name = getattr(channel, "name", "") or ""
        return "ticket" in name.lower()

    def _serialize_attachments(self, message: nextcord.Message) -> List[Dict[str, str]]:
        return [{
            "filename": a.filename,
            "url": a.url,
            "content_type": a.content_type or "",
        } for a in message.attachments]

    def _serialize_embeds(self, message: nextcord.Message) -> List[Dict[str, str]]:
        embeds: List[Dict[str, str]] = []
        for e in message.embeds:
            embeds.append({
                "title": e.title or "",
                "description": e.description or "",
                "url": e.url or "",
                "type": e.type or "",
            })
        return embeds

    def _ensure_ticket(self, message: nextcord.Message) -> TicketRecord:
        owner_id = message.author.id if not message.author.bot else None
        return self.store.ticket_get_or_create(
            channel_id=message.channel.id,
            guild_id=message.guild.id if message.guild else None,
            owner_id=owner_id,
        )

    def append_message_snapshot(self, message: nextcord.Message) -> None:
        if not self.is_ticket_channel(getattr(message, "channel", None)):
            return
        ticket = self._ensure_ticket(message)
        snapshot = TicketSnapshot(
            ticket_id=ticket.ticket_id,
            event_type="message",
            created_at=int(time.time()),
            guild_id=message.guild.id if message.guild else None,
            channel_id=message.channel.id,
            message_id=message.id,
            author_id=message.author.id,
            author_name=str(message.author),
            message_created_at=int(message.created_at.timestamp()),
            message_edited_at=int(message.edited_at.timestamp()) if message.edited_at else None,
            content=message.content or "",
            attachments=self._serialize_attachments(message),
            embeds=self._serialize_embeds(message),
        )
        self.store.ticket_append_snapshot(snapshot)

    def append_edit_snapshot(self, before: nextcord.Message, after: nextcord.Message) -> None:
        if not self.is_ticket_channel(getattr(after, "channel", None)):
            return
        ticket = self._ensure_ticket(after)
        snapshot = TicketSnapshot(
            ticket_id=ticket.ticket_id,
            event_type="message_edit",
            created_at=int(time.time()),
            guild_id=after.guild.id if after.guild else None,
            channel_id=after.channel.id,
            message_id=after.id,
            author_id=after.author.id,
            author_name=str(after.author),
            message_created_at=int(after.created_at.timestamp()),
            message_edited_at=int(after.edited_at.timestamp()) if after.edited_at else int(time.time()),
            content=after.content or "",
            previous_content=before.content or "",
            attachments=self._serialize_attachments(after),
            embeds=self._serialize_embeds(after),
        )
        self.store.ticket_append_snapshot(snapshot)

    def append_delete_snapshot(self, message: nextcord.Message) -> None:
        if not self.is_ticket_channel(getattr(message, "channel", None)):
            return
        ticket = self._ensure_ticket(message)
        snapshot = TicketSnapshot(
            ticket_id=ticket.ticket_id,
            event_type="message_delete",
            created_at=int(time.time()),
            guild_id=message.guild.id if message.guild else None,
            channel_id=message.channel.id,
            message_id=message.id,
            author_id=message.author.id if message.author else None,
            author_name=str(message.author) if message.author else "unknown",
            message_created_at=int(message.created_at.timestamp()) if message.created_at else None,
            message_edited_at=int(message.edited_at.timestamp()) if message.edited_at else None,
            content=message.content or "",
            attachments=self._serialize_attachments(message),
            embeds=self._serialize_embeds(message),
        )
        self.store.ticket_append_snapshot(snapshot)

    def _event_sort_key(self, s: TicketSnapshot) -> Tuple[int, int]:
        primary = s.message_created_at or s.message_edited_at or s.created_at
        secondary = s.message_id or 0
        return (primary, secondary)

    def build_transcript(self, ticket: TicketRecord) -> BuiltTranscript:
        snapshots = sorted(self.store.ticket_list_snapshots(ticket.ticket_id), key=self._event_sort_key)

        md_lines = [
            f"# Transcript ticket {ticket.ticket_id}",
            "",
            "## Métadonnées",
            f"- Owner: {ticket.owner_id or 'unknown'}",
            f"- Guild: {ticket.guild_id or 'unknown'}",
            f"- Channel: {ticket.channel_id}",
            f"- Created at: {ticket.created_at}",
            f"- Closed at: {ticket.closed_at or 'open'}",
            f"- Final status: {ticket.status}",
            "",
            "## Événements",
        ]

        html_parts = [
            "<html><head><meta charset='utf-8'><title>Ticket transcript</title></head><body>",
            f"<h1>Transcript ticket {escape(ticket.ticket_id)}</h1>",
            "<h2>Métadonnées</h2><ul>",
            f"<li>Owner: {ticket.owner_id or 'unknown'}</li>",
            f"<li>Guild: {ticket.guild_id or 'unknown'}</li>",
            f"<li>Channel: {ticket.channel_id}</li>",
            f"<li>Created at: {ticket.created_at}</li>",
            f"<li>Closed at: {ticket.closed_at or 'open'}</li>",
            f"<li>Final status: {escape(ticket.status)}</li>",
            "</ul><h2>Événements</h2>",
        ]

        for snapshot in snapshots:
            ts = snapshot.message_created_at or snapshot.created_at
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            md_lines.append(f"### [{dt}] {snapshot.event_type} — {snapshot.author_name} ({snapshot.author_id or 'unknown'})")
            if snapshot.previous_content:
                md_lines.append(f"- Previous: {snapshot.previous_content}")
            if snapshot.content:
                md_lines.append(f"- Content: {snapshot.content}")
            if snapshot.attachments:
                md_lines.append("- Attachments:")
                for a in snapshot.attachments:
                    md_lines.append(f"  - [{a.get('filename', 'file')}]({a.get('url', '')})")
            if snapshot.embeds:
                md_lines.append("- Embeds:")
                for e in snapshot.embeds:
                    md_lines.append(f"  - title={e.get('title', '')} url={e.get('url', '')}")
            md_lines.append("")

            html_parts.append(f"<article><h3>[{escape(dt)}] {escape(snapshot.event_type)} — {escape(snapshot.author_name)}</h3><ul>")
            if snapshot.previous_content:
                html_parts.append(f"<li><strong>Previous:</strong> {escape(snapshot.previous_content)}</li>")
            if snapshot.content:
                html_parts.append(f"<li><strong>Content:</strong> {escape(snapshot.content)}</li>")
            if snapshot.attachments:
                html_parts.append("<li><strong>Attachments:</strong><ul>")
                for a in snapshot.attachments:
                    html_parts.append(f"<li><a href='{escape(a.get('url', ''))}'>{escape(a.get('filename', 'file'))}</a></li>")
                html_parts.append("</ul></li>")
            if snapshot.embeds:
                html_parts.append("<li><strong>Embeds:</strong><ul>")
                for e in snapshot.embeds:
                    html_parts.append(f"<li>{escape(e.get('title', ''))} {escape(e.get('url', ''))}</li>")
                html_parts.append("</ul></li>")
            html_parts.append("</ul></article>")

        html_parts.append("</body></html>")
        markdown = "\n".join(md_lines)
        html = "".join(html_parts)

        os.makedirs(self.transcript_dir, exist_ok=True)
        md_path = os.path.join(self.transcript_dir, f"ticket-{ticket.ticket_id}.md")
        html_path = os.path.join(self.transcript_dir, f"ticket-{ticket.ticket_id}.html")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        return BuiltTranscript(markdown=markdown, html=html, path=md_path)

    def finalize_ticket(self, channel_id: int, status: str) -> Optional[TicketRecord]:
        ticket = self.store.ticket_get_by_channel(channel_id)
        if ticket is None:
            return None

        ticket.status = "closed" if status == "closed" else "deleted"
        ticket.closed_at = int(time.time())
        built = self.build_transcript(ticket)
        self.store.ticket_finalize(
            channel_id=channel_id,
            status=ticket.status,
            transcript_markdown=built.markdown,
            transcript_html=built.html,
            transcript_path=built.path,
        )

        self.store.ticket_append_snapshot(TicketSnapshot(
            ticket_id=ticket.ticket_id,
            event_type="ticket_closed" if status == "closed" else "ticket_deleted",
            created_at=int(time.time()),
            guild_id=ticket.guild_id,
            channel_id=ticket.channel_id,
            content=f"Ticket {status}",
        ))
        return ticket
