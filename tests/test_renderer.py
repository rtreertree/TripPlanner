"""Portable rendering and untrusted-content safety, without API credentials."""


import pytest

from trip_planner.models import SavedPlan
from trip_planner.renderer import open_plan, render_plan


def example_plan() -> SavedPlan:
    return SavedPlan.model_validate({
        "trip_id": "test-trip", "revision": 1,
        "created_at": "2026-11-04T10:00:00+00:00", "updated_at": "2026-11-04T10:00:00+00:00",
        "request": {"trip_name": "A day in 京都", "destinations": ["Kyoto"], "duration_days": 1,
                    "travelers": 2, "currency": "JPY", "budget": 10000, "preferences": "Temples & local food"},
        "summary": "An easy day discovering Kyoto together.",
        "days": [{
            "day_number": 1, "date": None, "title": "A gentle introduction", "summary": "Start slowly.",
            "destinations": ["Kyoto"],
            "schedule": [{"id": "visit-1", "kind": "activity", "title": "Temple gardens",
                "description": "Quiet paths fit a relaxed morning.", "start_time": "09:00", "end_time": "10:00",
                "start_timezone": "Asia/Tokyo", "end_timezone": "Asia/Tokyo", "start_day_offset": 0,
                "end_day_offset": 0, "duration_minutes": 60, "place_name": "Temple", "location": "Kyoto",
                "travel": None, "cost": {"category": "activities", "amount": 1000, "currency": "JPY"},
                "notes": ["Check opening hours."]},
                {"id": "travel-1", "kind": "travel", "title": "Walk to lunch", "description": "Allow a buffer.",
                 "start_time": "10:00", "end_time": "10:20", "start_timezone": "Asia/Tokyo",
                 "end_timezone": "Asia/Tokyo", "start_day_offset": 0, "end_day_offset": 0, "duration_minutes": 20,
                 "place_name": None, "location": None,
                 "travel": {"origin": "Temple", "destination": "Market", "transport_mode": "Walk",
                            "duration_minutes": 20, "route_notes": "Use the riverside path."},
                 "cost": {"category": "transport", "amount": 0, "currency": "JPY"}, "notes": []}],
            "additional_costs": [{"category": "accommodation", "amount": 6000, "currency": "JPY", "label": "Guesthouse"}],
            "estimated_total_cost": 7000, "notes": ["Comfortable shoes recommended."]}],
        "budget_summary": {"scope": "Meals, activities, accommodation and transport; excludes travel from home.",
            "category_totals": {"activities": 1000, "transport": 0, "accommodation": 6000}, "estimated_total": 7000,
            "budget_limit": 10000, "remaining": 3000, "currency": "JPY", "status": "within_budget", "partial": False},
        "assumptions": ["One shared room."], "warnings": ["All prices are estimates."],
        "generation": {"provider": "fixture", "model": "offline", "demo": True,
                       "generated_at": "2026-11-04T10:00:00+00:00"},
    })


def test_standalone_offline_page_is_readable_and_responsive(tmp_path):
    plan = example_plan()
    page = render_plan(plan, tmp_path / "trip" / "itinerary.html")
    html = page.read_text(encoding="utf-8")
    assert page.is_absolute()
    assert "A day in 京都" in html
    assert "JPY 7,000.00" in html and "JPY 3,000.00" in html
    assert "For 2 travelers across 1 days." in html
    assert "Demo" in html and "DEMO ITINERARY" in html
    assert "To change this plan, return to the terminal. Refresh this page after a change." in html
    assert "<style>" in html and "@media print" in html and "max-width: 520px" in html
    assert 'href="#day-1"' in html and 'id="day-1"' in html
    assert "<script" not in html and "<link" not in html and "<img" not in html
    assert "https://" not in html and "http://" not in html and "@import" not in html
    assert not list(page.parent.glob(".itinerary-*"))


TEXT_PATHS = [
    ("request", "trip_name"), ("request", "destinations", 0), ("request", "preferences"),
    ("summary",), ("days", 0, "title"), ("days", 0, "summary"), ("days", 0, "destinations", 0),
    ("days", 0, "schedule", 0, "title"), ("days", 0, "schedule", 0, "description"),
    ("days", 0, "schedule", 0, "place_name"), ("days", 0, "schedule", 0, "location"),
    ("days", 0, "schedule", 0, "start_timezone"), ("days", 0, "schedule", 0, "end_timezone"),
    ("days", 0, "schedule", 0, "start_time"), ("days", 0, "schedule", 0, "end_time"),
    ("days", 0, "schedule", 0, "notes", 0), ("days", 0, "schedule", 0, "cost", "currency"),
    ("days", 0, "schedule", 1, "travel", "origin"), ("days", 0, "schedule", 1, "travel", "destination"),
    ("days", 0, "schedule", 1, "travel", "transport_mode"), ("days", 0, "schedule", 1, "travel", "route_notes"),
    ("days", 0, "additional_costs", 0, "label"), ("days", 0, "notes", 0),
    ("budget_summary", "scope"), ("assumptions", 0), ("warnings", 0),
    ("generation", "model"), ("created_at",), ("updated_at",), ("generation", "generated_at"),
]


@pytest.mark.parametrize("path", TEXT_PATHS)
def test_untrusted_plan_text_is_escaped(path, tmp_path):
    data = example_plan().model_dump(mode="json")
    text = '<script>alert("unsafe")</script><b>Untrusted & content</b>'
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = text
    html = render_plan(SavedPlan.model_validate(data), tmp_path / "page.html").read_text()
    assert text not in html
    # Jinja's escape uses numeric quote entities; angle brackets establish that
    # the user/model text remains text rather than executable elements.
    assert "&lt;script&gt;" in html and "&lt;/script&gt;" in html
    assert "&lt;b&gt;Untrusted &amp; content&lt;/b&gt;" in html


def test_unknown_costs_remain_distinct_from_free_and_budget_is_uncertain(tmp_path):
    data = example_plan().model_dump(mode="json")
    data["days"][0]["schedule"][0]["cost"]["amount"] = None
    data["budget_summary"].update(partial=True, status="uncertain", estimated_total=6000)
    html = render_plan(SavedPlan.model_validate(data), tmp_path / "page.html").read_text()
    assert "Unknown" in html and "JPY 0.00 · Free" in html
    assert "partial" in html and "PARTIAL ESTIMATED GROUP TOTAL" in html
    assert "budget status is uncertain" in html


@pytest.mark.parametrize("limit, status, expected", [
    (5000, "over_budget", "Over your budget by JPY 2,000.00"),
    (None, "no_limit", "No spending limit set."),
])
def test_budget_states(limit, status, expected, tmp_path):
    data = example_plan().model_dump(mode="json")
    data["budget_summary"].update(budget_limit=limit, remaining=None if limit is None else limit - 7000, status=status)
    html = render_plan(SavedPlan.model_validate(data), tmp_path / "page.html").read_text()
    assert expected in html


def test_failed_atomic_replace_preserves_previous_page_and_cleans_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "itinerary.html"
    path.write_text("Last saved page")
    def fail_replace(source, destination):
        raise PermissionError("Read-only destination")
    monkeypatch.setattr("trip_planner.renderer.os.replace", fail_replace)
    with pytest.raises(PermissionError):
        render_plan(example_plan(), path)
    assert path.read_text() == "Last saved page"
    assert sorted(file.name for file in tmp_path.iterdir()) == ["itinerary.html"]


def test_open_plan_uses_file_uri(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr("trip_planner.renderer.webbrowser.open", lambda uri: opened.append(uri) or False)
    assert open_plan(tmp_path / "with spaces.html") is False
    assert opened == [(tmp_path / "with spaces.html").as_uri()]
