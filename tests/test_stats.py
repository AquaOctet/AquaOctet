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


def test_language_share_weights_by_pushes_and_aliases():
    by_project = {1: {"TSX": 60.0, "TypeScript": 40.0}, 2: {"Go Template": 100.0}, 3: {"Rust": 100.0}}
    weights = {1: 3, 2: 1, 3: 0}
    share = gs.language_share(by_project, weights)
    assert share[0] == ("TypeScript", 75.0)
    assert share[1] == ("Helm", 25.0)
    assert all(name != "Rust" for name, _ in share)  # zero pushes contribute nothing


def test_language_share_folds_tail_into_other():
    by_project = {1: {f"L{i}": 10.0 for i in range(10)}}
    share = gs.language_share(by_project, {1: 1})
    assert len(share) == gs.LANG_TOP + 1 and share[-1][0] == "Other"
    assert abs(sum(v for _, v in share) - 100) < 0.5


SITEMAP = """<urlset>
<url><loc>https://x.pages.dev/</loc></url>
<url><loc>https://x.pages.dev/posts/old</loc><lastmod>2024-01-01T00:00:00.000Z</lastmod></url>
<url><loc>https://x.pages.dev/posts/new</loc><lastmod>2026-09-19T00:00:00.000Z</lastmod></url>
</urlset>"""


def test_latest_post_from_sitemap_picks_newest_and_rewrites_host():
    post = gs.latest_post_from_sitemap(SITEMAP, "https://aquaoctet.com")
    assert post == {"url": "https://aquaoctet.com/posts/new", "date": "2026-09-19"}


def test_parse_post_meta_prefers_open_graph():
    html = '<title>Fallback :: Site</title><meta property="og:title" content="Real &amp; Title"/>' \
           '<meta name="description" content="Desc"/>'
    assert gs.parse_post_meta(html) == {"title": "Real & Title", "description": "Desc"}


def test_update_readme_replaces_only_marked_block():
    text = f"intro\n{gs.README_START}\nold\n{gs.README_END}\noutro\n"
    post = {"title": "T", "url": "https://s/posts/t", "date": "2026-09-19", "description": "D"}
    out = gs.update_readme(text, post)
    assert out.startswith("intro\n") and out.endswith("\noutro\n")
    assert "old" not in out and "[T](https://s/posts/t)" in out and "D" in out
    assert gs.update_readme("no markers", post) == "no markers"
    assert gs.update_readme(text, None) == text
