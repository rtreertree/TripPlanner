import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from trip_planner.cli import main, read_answers
from trip_planner.demo import demo_plan
from trip_planner.storage import Session, Store, atomic_json


def test_atomic_write_failure_preserves_previous_content(tmp_path, monkeypatch):
    path = tmp_path / "plan.json"
    atomic_json(path, {"revision": 1})
    monkeypatch.setattr("trip_planner.storage.os.replace", Mock(side_effect=PermissionError))
    with pytest.raises(PermissionError):
        atomic_json(path, {"revision": 2})
    assert json.loads(path.read_text()) == {"revision": 1}
    assert not list(tmp_path.glob(".pending-*"))


def test_plan_save_and_load_unicode_and_history(tmp_path):
    store = Store(tmp_path)
    plan = demo_plan()
    plan.request.trip_name = "京都 · วันหยุด"
    store.save_plan(plan)
    assert store.load_plan(plan.trip_id) == plan
    assert (store.directory(plan.trip_id) / "request.json").exists()
    assert (store.directory(plan.trip_id) / "revisions" / "0001.json").exists()


@pytest.mark.parametrize("trip_id", ["../escape", "/tmp", "a/b", "", "a\\b"])
def test_storage_rejects_unsafe_identifiers(tmp_path, trip_id):
    with pytest.raises(ValueError):
        Store(tmp_path).directory(trip_id)


def test_session_restores_raw_answers_skips_draft_prompt_and_pending(tmp_path):
    session = Session(answers={"trip_name": "", "duration_days": "a week"}, skipped=["trip_name"],
                      prompt_index=2, pending={"message": "add another person"})
    store = Store(tmp_path)
    store.save_session(session)
    assert store.load_session(session.trip_id) == session
    assert store.list_trips()[0]["status"] == "Draft"


def test_corrupt_saved_trip_is_reported_without_destroying_it(tmp_path):
    folder = tmp_path / "broken"
    folder.mkdir()
    path = folder / "session.json"
    path.write_text("broken")
    store = Store(tmp_path)
    assert store.list_trips() == []
    assert store.warnings and path.read_text() == "broken"


def test_tampered_totals_rejected_on_load(tmp_path):
    store = Store(tmp_path)
    plan = demo_plan()
    store.save_plan(plan)
    path = store.directory(plan.trip_id) / "plan.json"
    data = json.loads(path.read_text())
    data["budget_summary"]["estimated_total"] = 0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="totals"):
        store.load_plan(plan.trip_id)


def test_demo_and_render_do_not_require_configuration(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("trip_planner.config.Config.validate_live", Mock(side_effect=AssertionError("must remain offline")))
    assert main(["demo", "--no-open", "--output-dir", str(tmp_path)]) == 0
    plan_path = next(tmp_path.glob("*/plan.json"))
    assert main(["render", "--plan", str(plan_path), "--no-open"]) == 0
    page = plan_path.with_name("itinerary.html").read_text()
    assert "To change this plan, return to the terminal" in page
    assert "Offline demo" in capsys.readouterr().out


def test_text_utility_preserves_labels_and_multiline_natural_answers(tmp_path):
    path = tmp_path / "answers.txt"
    path.write_text("Trip name: 京都\nDays: a week\nDestinations: Tokyo then Kyoto\nBudget: 150000 yen\nPreferences / special requests: local food\n  Two travelers, avoid nightlife.\n", encoding="utf-8")
    answers = read_answers(path)
    assert answers["duration_days"] == "a week"
    assert "Two travelers" in answers["preferences"]
    assert answers["trip_name"] == "京都"
