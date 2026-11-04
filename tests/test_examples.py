import json
from pathlib import Path

from trip_planner.models import InterpreterResult, PlannerResult, SavedPlan, TripRequest
from trip_planner.validation import validate_plan

ROOT = Path(__file__).resolve().parents[1]


def test_delivered_example_is_a_complete_valid_plan():
    plan = validate_plan(SavedPlan.model_validate_json((ROOT / "examples" / "plan.json").read_text()))
    assert plan.generation.demo
    assert plan.request == TripRequest.model_validate_json((ROOT / "examples" / "request.json").read_text())
    assert (ROOT / "examples" / "itinerary.html").exists()


def test_exported_schemas_match_authoritative_models():
    contracts = {"interpreter_result": InterpreterResult, "planner_result": PlannerResult,
                 "trip_request": TripRequest, "saved_plan": SavedPlan}
    for name, model in contracts.items():
        exported = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        assert exported == model.model_json_schema()
