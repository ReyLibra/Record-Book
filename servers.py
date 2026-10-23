"""Genshin's game servers and their clocks: daily resets, domain days and endgame schedules all go by
the server's own time (each server is a fixed offset from UTC; the daily reset is at 4:00 there)."""

from datetime import datetime, timedelta, timezone

SERVERS = [("America", -5), ("Europe", 1), ("Asia", 8), ("TW, HK, MO", 8)]
DEFAULT = "America"
RESET_HOUR = 4
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def offset(server):
    return timezone(timedelta(hours=dict(SERVERS).get(server, -5)))


def now(server):
    """The time on the server's clock right now (timezone-aware)."""
    return datetime.now(offset(server))


def game_weekday(server):
    """Today's weekday in the game (0 = Monday): it changes at the 4:00 daily reset, not at midnight."""
    return (now(server) - timedelta(hours=RESET_HOUR)).weekday()


def countdown(end, start=None):
    """'12d 4h', '5h 12m' or '3m' until end (a datetime) from start (default: now)."""
    start = start or datetime.now(timezone.utc)
    left = max(0, int((end - start).total_seconds()))
    days, rest = divmod(left, 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {rest // 60}m"
    return f"{rest // 60}m"
