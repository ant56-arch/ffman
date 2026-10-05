"""Optional push notifications (ntfy.sh phone alerts or a Discord webhook)."""

from __future__ import annotations

import json
import urllib.request

from .http import USER_AGENT
from .report import LeagueReport


def summary(reports: list[LeagueReport], week: int | None) -> str:
    todo = [r for r in reports if r.needs_changes]
    head = f"Week {week}: " if week else ""
    if not todo:
        return f"{head}all {len(reports)} lineups look good."
    lines = [f"{head}{len(todo)} of {len(reports)} leagues need changes"]
    for r in todo:
        lines.append(f"\n{r.team.league_name} (+{r.gain:.1f}):")
        for player, benched in r.start:
            lines.append(f"  Start {player.name}" + (f" over {benched.name}" if benched else ""))
    warnings = [w for r in reports for w in r.warnings]
    if warnings:
        lines.append(f"\n{len(warnings)} injury/bye warnings - see full report.")
    return "\n".join(lines)


def _post(url: str, body: bytes, headers: dict) -> None:
    request = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT, **headers})
    with urllib.request.urlopen(request, timeout=30):
        pass


def send(config: dict, text: str) -> list[str]:
    """Send to every configured channel; returns the channels used."""
    sent = []
    if topic := config.get("ntfy_topic"):
        server = config.get("ntfy_server", "https://ntfy.sh").rstrip("/")
        _post(f"{server}/{topic}", text.encode(), {"Title": "Fantasy lineup check"})
        sent.append("ntfy")
    if webhook := config.get("discord_webhook"):
        for start in range(0, len(text), 1900):  # Discord caps messages at 2000 chars
            payload = json.dumps({"content": text[start:start + 1900]}).encode()
            _post(webhook, payload, {"Content-Type": "application/json"})
        sent.append("discord")
    return sent
