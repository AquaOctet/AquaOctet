import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gitlab_stats as gs  # noqa: E402

TODAY = dt.date(2026, 9, 25)


def ev(action, day, target=None, commits=None, project=1):
    e = {"action_name": action, "created_at": f"{day}T10:00:00Z", "target_type": target, "project_id": project}
    if commits is not None:
        e["push_data"] = {"commit_count": commits}
    return e


EVENTS = [
    ev("pushed to", "2026-09-25", "Project", commits=3),
    ev("pushed new", "2026-09-24", "Project", commits=0),
    ev("accepted", "2026-09-24", "MergeRequest"),
    ev("opened", "2026-09-23", "MergeRequest", project=2),
    ev("closed", "2026-09-20", "Issue", project=3),
    ev("opened", "2026-09-20", "Issue"),
    ev("deleted", "2026-09-25", "Project", project=9),  # not counted
]


def test_aggregate_counts():
    s = gs.aggregate(EVENTS, TODAY)
    assert s["commits"] == 3
    assert s["mrs_merged"] == 1 and s["mrs_opened"] == 1
    assert s["issues_closed"] == 1 and s["issues_opened"] == 1
    assert s["projects"] == 3  # deleted-branch project excluded
    assert s["active_days"] == 4
    assert s["per_day"]["2026-09-24"] == 2  # empty push counts once, plus MR


def test_streaks():
    s = gs.aggregate(EVENTS, TODAY)
    assert s["current_streak"] == 3  # 23, 24, 25
    assert s["longest_streak"] == 3


def test_streak_allows_nothing_yet_today():
    s = gs.aggregate([e for e in EVENTS if not e["created_at"].startswith("2026-09-25")], TODAY)
    assert s["current_streak"] == 2


def test_render_both_themes_contains_cells_and_no_project_names():
    s = gs.aggregate(EVENTS, TODAY)
    for theme in ("light", "dark"):
        svg = gs.render_svg(s, TODAY, theme, "someone")
        assert svg.startswith("<svg")
        assert svg.count("<rect") >= 52 * 7  # a year of cells plus chrome
        assert "@someone" in svg
        assert "2026-09-25: 3 contributions" in svg
