"""Optional push notifications (ntfy.sh phone alerts or a Discord webhook)."""

from __future__ import annotations

import json
import urllib.request

from .http import USER_AGENT
from .report import LeagueReport, deadline_label, game_plan


def summary(reports: list[LeagueReport], week: int | None) -> str:
    plan = game_plan(reports)
    head = f"Week {week}: " if week else ""
    if not plan.moves and not plan.pickups and not plan.watch:
        return f"{head}all {len(reports)} lineups look good."
    lines = [f"{head}{len({id(r) for r, _ in plan.moves})} of {len(reports)} leagues need changes"]
    current = None
    for r, m in plan.moves:
        label = deadline_label(m.deadline)
        if label != current:
            lines.append(f"\n{label}:")
            current = label
        over = f" over {m.benched.name}" if m.benched else ""
        close = " (close call)" if m.close_call else ""
        lines.append(f"  {r.team.league_name}: start {m.player.name}{over} +{m.gain:.1f}{close}")
    if plan.pickups:
        lines.append("\nPickups needed:")
        lines.extend(f"  {r.team.league_name}: {a.text}" for r, a in plan.pickups)
    if plan.watch:
        lines.append("\nWatch:")
        lines.extend(f"  {r.team.league_name}: {a.text}" for r, a in plan.watch)
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
