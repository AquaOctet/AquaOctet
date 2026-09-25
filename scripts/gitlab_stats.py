#!/usr/bin/env python3
"""Render a GitLab activity card (SVG) from the user events API.

Reads GITLAB_TOKEN (read access on User events) and GITLAB_USER_ID from the
environment, fetches the last 52 weeks of events, aggregates them, and writes
light and dark SVG cards plus a stats.json snapshot into the assets directory.
Only aggregates are written; project names never leave the script.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

API = os.environ.get("GITLAB_API", "https://gitlab.com/api/v4")
WEEKS = 52

# Events that count as a contribution. Branch deletions and the like are noise.
COUNTED = {"pushed to", "pushed new", "opened", "accepted", "closed", "merged",
           "created", "commented on", "approved"}


# ----------------------------------------------------------------- fetching

def fetch_events(token: str, user_id: int, after: dt.date) -> list[dict]:
    events: list[dict] = []
    page = 1
    while True:
        qs = urllib.parse.urlencode({"after": after.isoformat(), "per_page": 100, "page": page})
        req = urllib.request.Request(f"{API}/users/{user_id}/events?{qs}",
                                     headers={"PRIVATE-TOKEN": token})
        with urllib.request.urlopen(req, timeout=60) as resp:
            events.extend(json.load(resp))
            nxt = resp.headers.get("X-Next-Page")
        if not nxt:
            return events
        page = int(nxt)


# -------------------------------------------------------------- aggregating

def aggregate(events: list[dict], today: dt.date) -> dict:
    """Reduce raw events to the numbers the card shows."""
    counted = [e for e in events if e["action_name"] in COUNTED]
    per_day: Counter[str] = Counter()
    commits = 0
    mrs_merged = mrs_opened = issues_opened = issues_closed = 0
    for e in counted:
        day = e["created_at"][:10]
        action, target = e["action_name"], e.get("target_type")
        if action.startswith("pushed"):
            n = (e.get("push_data") or {}).get("commit_count") or 0
            commits += n
            per_day[day] += max(n, 1)
        else:
            per_day[day] += 1
        if target == "MergeRequest":
            mrs_opened += action == "opened"
            mrs_merged += action in ("accepted", "merged")
        elif target == "Issue":
            issues_opened += action == "opened"
            issues_closed += action == "closed"

    return {
        "generated": today.isoformat(),
        "commits": commits,
        "mrs_merged": mrs_merged,
        "mrs_opened": mrs_opened,
        "issues_opened": issues_opened,
        "issues_closed": issues_closed,
        "projects": len({e["project_id"] for e in counted}),
        "active_days": len(per_day),
        "current_streak": streak(per_day, today),
        "longest_streak": longest_streak(per_day),
        "per_day": dict(sorted(per_day.items())),
    }


def streak(per_day: Counter, today: dt.date) -> int:
    day = today if per_day.get(today.isoformat()) else today - dt.timedelta(days=1)
    n = 0
    while per_day.get(day.isoformat()):
        n += 1
        day -= dt.timedelta(days=1)
    return n


def longest_streak(per_day: Counter) -> int:
    best = run = 0
    prev: dt.date | None = None
    for key in sorted(per_day):
        day = dt.date.fromisoformat(key)
        run = run + 1 if prev and day - prev == dt.timedelta(days=1) else 1
        best = max(best, run)
        prev = day
    return best


# ---------------------------------------------------------------- rendering

THEMES = {
    # Sequential one-hue ramp (blue), lightest step means "near zero".
    "light": dict(bg="#ffffff", border="#d8dee4", text="#1f2328", muted="#656d76",
                  accent="#e24329", zero="#eef1f4",
                  ramp=["#b7d3f6", "#6da7ec", "#2a78d6", "#184f95"]),
    "dark": dict(bg="#0d1117", border="#30363d", text="#e6edf3", muted="#8b949e",
                 accent="#fc6d26", zero="#1c2128",
                 ramp=["#184f95", "#2a78d6", "#6da7ec", "#b7d3f6"]),
}
CELL, GAP = 11, 3
LEFT, TOP = 24, 118
WIDTH = LEFT + WEEKS * (CELL + GAP) + 20
HEIGHT = TOP + 7 * (CELL + GAP) + 40


def level(count: int, thresholds: list[int]) -> int:
    if count <= 0:
        return 0
    return 1 + sum(count > t for t in thresholds[:3])


def quartile_thresholds(per_day: dict[str, int]) -> list[int]:
    vals = sorted(v for v in per_day.values() if v > 0)
    if not vals:
        return [0, 0, 0]
    q = lambda p: vals[min(len(vals) - 1, int(len(vals) * p))]  # noqa: E731
    return [q(0.25), q(0.5), q(0.75)]


def render_svg(stats: dict, today: dt.date, theme: str, username: str) -> str:
    t = THEMES[theme]
    per_day = stats["per_day"]
    thresholds = quartile_thresholds(per_day)
    # Grid ends on today's week (Sunday-start columns).
    end = today
    start = end - dt.timedelta(days=WEEKS * 7 - 1)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)  # back to Sunday

    cells, month_labels = [], []
    seen_month = None
    day = start
    col = 0
    while day <= end:
        for row in range(7):
            if day > end:
                break
            key = day.isoformat()
            n = per_day.get(key, 0)
            fill = t["zero"] if n == 0 else t["ramp"][level(n, thresholds) - 1]
            x = LEFT + col * (CELL + GAP)
            y = TOP + row * (CELL + GAP)
            cells.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{fill}">'
                         f'<title>{key}: {n} contribution{"s" if n != 1 else ""}</title></rect>')
            if row == 0 and day.month != seen_month:
                if seen_month is not None or day.day <= 7:
                    month_labels.append(f'<text x="{x}" y="{TOP - 8}" class="muted">{day.strftime("%b")}</text>')
                seen_month = day.month
            day += dt.timedelta(days=1)
        col += 1

    tiles = [("Commits", stats["commits"]), ("MRs merged", stats["mrs_merged"]),
             ("Issues closed", stats["issues_closed"]), ("Projects", stats["projects"]),
             ("Active days", stats["active_days"]), ("Streak", f'{stats["current_streak"]}d')]
    tile_w = (WIDTH - LEFT * 2) / len(tiles)
    tile_svg = "".join(
        f'<text x="{LEFT + i * tile_w:.0f}" y="66" class="num">{v}</text>'
        f'<text x="{LEFT + i * tile_w:.0f}" y="82" class="muted">{k}</text>'
        for i, (k, v) in enumerate(tiles))

    legend_x = WIDTH - LEFT - 4 * (CELL + GAP) - 60
    legend_y = HEIGHT - 22
    legend = f'<text x="{legend_x - 30}" y="{legend_y + 9}" class="muted">Less</text>' + "".join(
        f'<rect x="{legend_x + i * (CELL + GAP)}" y="{legend_y}" width="{CELL}" height="{CELL}" rx="2" fill="{c}"/>'
        for i, c in enumerate([t["zero"], *t["ramp"]])) + \
        f'<text x="{legend_x + 5 * (CELL + GAP) + 2}" y="{legend_y + 9}" class="muted">More</text>'

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="GitLab activity for {username}: {stats["commits"]} commits in the last year">
<style>
text{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;font-size:11px;fill:{t["text"]}}}
.title{{font-size:15px;font-weight:600}} .num{{font-size:18px;font-weight:600}} .muted{{fill:{t["muted"]};font-size:10px}}
</style>
<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="8" fill="{t["bg"]}" stroke="{t["border"]}"/>
<path transform="translate({LEFT},14) scale(0.9)" fill="{t["accent"]}" d="M18.5 8.1 15.9 0.2c-.1-.3-.6-.3-.7 0L12.6 8.1H6.4L3.8.2c-.1-.3-.6-.3-.7 0L.5 8.1c-.1.3 0 .6.2.8l8.8 6.4 8.8-6.4c.3-.2.4-.5.2-.8z"/>
<text x="{LEFT + 24}" y="26" class="title">GitLab activity · @{username}</text>
<text x="{WIDTH - LEFT}" y="26" text-anchor="end" class="muted">last 52 weeks · updated {stats["generated"]}</text>
{tile_svg}
{"".join(month_labels)}
<text x="{LEFT - 6}" y="{TOP + 1 * (CELL + GAP) + 9}" text-anchor="end" class="muted">M</text>
<text x="{LEFT - 6}" y="{TOP + 3 * (CELL + GAP) + 9}" text-anchor="end" class="muted">W</text>
<text x="{LEFT - 6}" y="{TOP + 5 * (CELL + GAP) + 9}" text-anchor="end" class="muted">F</text>
{"".join(cells)}
<text x="{LEFT}" y="{HEIGHT - 13}" class="muted">Longest streak {stats["longest_streak"]} days · {stats["mrs_opened"]} MRs opened · {stats["issues_opened"]} issues opened</text>
{legend}
</svg>
'''


# --------------------------------------------------------------------- main

def main() -> int:
    token = os.environ.get("GITLAB_TOKEN")
    user_id = int(os.environ["GITLAB_USER_ID"])
    username = os.environ.get("GITLAB_USERNAME", str(user_id))
    out = Path(os.environ.get("OUT_DIR", "assets"))
    if not token:
        print("GITLAB_TOKEN is not set", file=sys.stderr)
        return 1
    today = dt.date.today()
    events = fetch_events(token, user_id, today - dt.timedelta(days=WEEKS * 7 + 7))
    stats = aggregate(events, today)
    out.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        (out / f"gitlab-stats-{theme}.svg").write_text(render_svg(stats, today, theme, username))
    public = {k: v for k, v in stats.items() if k != "per_day"}
    (out / "stats.json").write_text(json.dumps(public, indent=2) + "\n")
    print(json.dumps(public, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
