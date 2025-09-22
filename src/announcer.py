# ===============================
# src/announcer.py
# ===============================
# src/announcer.py — events (MG/ZS) + VS reminder + weekly calendar
from __future__ import annotations
import discord
from datetime import datetime
from .config import MENTION_URGENT

# Toggle para usar @everyone como palabra clave fija
USE_EVERYONE = True

# Allowed mentions
ALLOWED_SAFE = discord.AllowedMentions(roles=True, users=False, everyone=False)
ALLOWED_WITH_EVERYONE = discord.AllowedMentions(roles=True, users=False, everyone=True)


def _fmt_eta(delta_seconds: int) -> str:
    s = max(0, delta_seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if not parts:
        parts.append("<1m")
    return " ".join(parts)


async def send_vs_register_reminder(channel, server_date_str: str):
    await channel.send(
        f"⏳ **VS — {server_date_str}**\n"
        f"Últimos **15 min** del día (server). Registra los puntos del VS con `/points <name> <amount>`."
    )


async def send_event_before(channel, event_code: str, event_full: str,
                            server_date_str: str, server_time_str: str,
                            eta_seconds: int):
    eta = _fmt_eta(eta_seconds)
    await channel.send(
        f"⏰ {event_code} — {server_date_str} {server_time_str} (server)\n"
        f"Starts in {eta}\n"
        f"*{event_full}*"
    )


async def send_event_before_urgent(channel,
                                   event_code: str,
                                   event_full: str,
                                   server_date_str: str,
                                   server_time_str: str,
                                   eta_seconds: int,
                                   final: bool = False):
    eta = _fmt_eta(eta_seconds)
    call = "final call!" if final else "be ready!"

    # Prefijo con roles desde .env
    prefix_parts = []
    if MENTION_URGENT:
        prefix_parts.append(MENTION_URGENT)
    if USE_EVERYONE:
        prefix_parts.append("@everyone")

    prefix = " ".join(prefix_parts) + " " if prefix_parts else ""

    # AllowedMentions según si usamos everyone
    allowed = ALLOWED_WITH_EVERYONE if USE_EVERYONE else ALLOWED_SAFE

    content = (
        f"{prefix}🚨 {event_code} — {server_date_str} {server_time_str} (server)\n"
        f"⚠️ Starts in {eta} — {call}\n"
        f"*{event_full}*"
    ).strip()

    try:
        await channel.send(content=content, allowed_mentions=allowed)
    except discord.Forbidden:
        # Fallback: reenviar sin mentions
        safe = content.replace("@everyone", "").strip()
        await channel.send(content=safe, allowed_mentions=ALLOWED_SAFE)


async def send_week_calendar(channel, entries):
    # entries: list of (day_label, time_label, label)
    if not entries:
        return
    lines = "\n".join(f"• {d} at {t} — {label}" for d, t, label in entries)
    await channel.send("📅 **This Week's Event Calendar**\n" + lines)
