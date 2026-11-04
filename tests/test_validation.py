from datetime import date

import pytest
from pydantic import ValidationError

from trip_planner.demo import demo_plan
from trip_planner.models import RequestDraft
from trip_planner.validation import build_plan, normalize_request, payload_from_plan, validate_plan


def test_request_defaults_unicode_and_destination_order():
    request = normalize_request(RequestDraft(destinations=[" 京都 ", "Tokyo", "京都", "tokyo"], duration_days=3,
                                             destination_currencies=["JPY", "JPY"]))
    assert request.destinations == ["京都", "Tokyo"]
    assert request.travelers == 1 and request.pace == "balanced" and request.currency == "JPY"
    assert request.budget is None and request.start_date is None


@pytest.mark.parametrize("changes,match", [
    ({"destinations": []}, "Where"),
    ({"duration_days": None}, "How many days"),
    ({"duration_days": 0}, "at least one"),
    ({"duration_days": 22}, "up to 21"),
    ({"travelers": 0}, "at least one traveler"),
    ({"budget": -1}, "positive budget"),
    ({"budget": 10}, "Which currency"),
    ({"currency": "$"}, "currency code"),
])
def test_material_request_errors(changes, match):
    data = {"destinations": ["Tokyo"], "duration_days": 3} | changes
    with pytest.raises(ValueError, match=match):
        normalize_request(RequestDraft(**data))


def test_per_person_budget_requires_explicit_travelers_and_converts_once():
    data = dict(destinations=["Tokyo"], duration_days=3, budget=100, currency="USD", budget_per_person=True)
    with pytest.raises(ValueError, match="How many people"):
        normalize_request(RequestDraft(**data))
    with pytest.raises(ValueError, match="How many people"):
        normalize_request(RequestDraft(**data, travelers=1, travelers_explicit=False))
    with pytest.raises(ValueError, match="How many people"):
        normalize_request(RequestDraft(**data, travelers=1))
    request = normalize_request(RequestDraft(**data, travelers=3, travelers_explicit=True))
    assert request.budget == 300
    revised = normalize_request(RequestDraft(**request.model_dump(exclude={"travelers"}), travelers=4))
    assert revised.budget == 300


def test_models_reject_extra_fields_and_nonfinite_money():
    with pytest.raises(ValidationError):
        RequestDraft(destination="Tokyo")
    with pytest.raises(ValidationError):
        RequestDraft(budget=float("inf"))


@pytest.mark.parametrize("destinations,currencies,expected", [
    (["Tokyo", "Kyoto"], ["JPY", "JPY"], "JPY"),
    (["Paris", "Rome"], ["EUR", "EUR"], "EUR"),
    (["Tokyo", "Seoul"], ["JPY", "KRW"], "THB"),
    (["Tokyo", "Bangkok"], ["JPY", "THB"], "THB"),
    (["Bangkok"], [" thb "], "THB"),
])
def test_estimates_use_local_currency_or_thb_for_different_currencies(destinations, currencies, expected):
    request = normalize_request(RequestDraft(destinations=destinations, duration_days=3,
                                             destination_currencies=currencies))
    assert request.currency == expected
    assert request.budget is None


def test_explicit_reporting_currency_overrides_destination_default():
    request = normalize_request(RequestDraft(destinations=["Tokyo", "Seoul"], duration_days=3,
                                             destination_currencies=["JPY", "KRW"], currency="EUR", budget=1500))
    assert request.currency == "EUR" and request.budget == 1500


def test_ambiguous_budget_is_not_guessed_from_local_currencies():
    with pytest.raises(ValueError, match="currency is your budget"):
        normalize_request(RequestDraft(destinations=["Tokyo"], duration_days=3,
                                       destination_currencies=["JPY"], budget=500))


def test_unknown_destination_currency_requires_clarification():
    with pytest.raises(ValueError, match="Which local currency"):
        normalize_request(RequestDraft(destinations=["Somewhere"], duration_days=3))


def test_invalid_destination_currency_is_rejected():
    with pytest.raises(ValueError, match="local currencies"):
        normalize_request(RequestDraft(destinations=["Tokyo"], duration_days=3,
                                       destination_currencies=["Japanese yen"]))


def test_demo_validates_and_computes_itemized_totals():
    plan = demo_plan()
    assert validate_plan(plan) is plan
    assert plan.budget_summary.estimated_total == 65820
    assert sum(day.estimated_total_cost for day in plan.days) == 65820
    assert sum(plan.budget_summary.category_totals.values()) == 65820
    assert plan.generation.demo and plan.revision == 1
    assert all(item.id for day in plan.days for item in day.schedule)


@pytest.mark.parametrize("mutation,match", [
    (lambda p: p.days.pop(), "exactly 3"),
    (lambda p: setattr(p.days[0], "day_number", 3), "consecutively"),
    (lambda p: setattr(p.days[0].schedule[1], "start_time", "10:30"), "inconsistent|overlap"),
    (lambda p: setattr(p.days[0].schedule[0], "duration_minutes", 1), "inconsistent"),
    (lambda p: p.days[0].schedule.pop(1), "transfer"),
    (lambda p: setattr(p.days[0].schedule[1].travel, "duration_minutes", 60), "enough scheduled"),
    (lambda p: setattr(p.days[0].schedule[1].travel, "origin", "Paris"), "origin"),
    (lambda p: setattr(p.days[0].schedule[0].cost, "currency", "USD"), "reporting currency"),
    (lambda p: setattr(p.days[0].schedule[0].cost, "amount", -1), "negative"),
    (lambda p: setattr(p.days[0], "date", date(2027, 1, 1)), "dates"),
    (lambda p: setattr(p.days[0].schedule[0], "start_timezone", "Mars/Olympus"), "timezone"),
    (lambda p: setattr(p.days[0].schedule[0], "start_time", "25:00"), "HH:MM"),
])
def test_invalid_candidates_are_rejected(mutation, match):
    plan = demo_plan()
    payload = payload_from_plan(plan)
    mutation(payload)
    with pytest.raises(ValueError, match=match):
        build_plan(payload, plan.request, plan.trip_id, previous=plan)
    assert validate_plan(plan) is plan


def test_requested_destination_cannot_silently_disappear():
    plan = demo_plan()
    request = plan.request.model_copy(update={"destinations": ["Tokyo", "Kyoto", "Osaka"]})
    with pytest.raises(ValueError, match="Osaka"):
        build_plan(payload_from_plan(plan), request, plan.trip_id)


def test_unknown_costs_are_partial_and_never_free():
    plan = demo_plan()
    payload = payload_from_plan(plan)
    payload.days[0].additional_costs[0].amount = None
    candidate = build_plan(payload, plan.request, plan.trip_id)
    assert candidate.budget_summary.estimated_total == 54820
    assert candidate.budget_summary.partial and candidate.budget_summary.status == "uncertain"
    assert any("unknown" in warning for warning in candidate.warnings)


def test_over_budget_is_valid_and_disclosed():
    plan = demo_plan()
    request = plan.request.model_copy(update={"budget": 100})
    candidate = build_plan(payload_from_plan(plan), request, plan.trip_id)
    assert candidate.budget_summary.status == "over_budget"
    assert candidate.budget_summary.remaining == -65720
    assert any("exceeds" in warning and "Consider" in warning for warning in candidate.warnings)


def test_money_sums_are_decimal_safe():
    plan = demo_plan()
    payload = payload_from_plan(plan)
    for day in payload.days:
        for cost in [item.cost for item in day.schedule] + day.additional_costs:
            cost.amount = 0
    payload.days[0].schedule[0].cost.amount = 0.1
    payload.days[0].schedule[1].cost.amount = 0.2
    candidate = build_plan(payload, plan.request, plan.trip_id)
    assert candidate.budget_summary.estimated_total == 0.3


def test_revision_identity_and_undo_ids():
    plan = demo_plan()
    payload = payload_from_plan(plan)
    payload.days[0].schedule[0].id = None
    candidate = build_plan(payload, plan.request, plan.trip_id, previous=plan)
    assert candidate.revision == 2 and candidate.created_at == plan.created_at
    assert candidate.days[0].schedule[0].id == plan.days[0].schedule[0].id
    restored = build_plan(payload_from_plan(plan), plan.request, plan.trip_id, previous=candidate, restored_from=plan)
    assert restored.revision == 3
    assert restored.days[0].schedule[0].id == plan.days[0].schedule[0].id
    with pytest.raises(ValueError, match="identity"):
        build_plan(payload, plan.request, "different-id", previous=plan)


def test_persisted_inconsistent_totals_rejected():
    plan = demo_plan()
    plan.days[0].estimated_total_cost += 1
    with pytest.raises(ValueError, match="totals"):
        validate_plan(plan)


def test_timezone_changes_and_midnight_offsets_are_respected():
    plan = demo_plan()
    payload = payload_from_plan(plan)
    first = payload.days[0].schedule[0]
    first.end_timezone = "Asia/Shanghai"
    first.end_time = "10:00"
    # 09:00 Tokyo -> 10:00 Shanghai is exactly two elapsed hours.
    assert build_plan(payload, plan.request, plan.trip_id)
    dinner = payload.days[0].schedule[-1]
    dinner.end_time = "01:00"
    dinner.end_day_offset = 1
    dinner.duration_minutes = 450
    assert build_plan(payload, plan.request, plan.trip_id)


def test_start_date_populates_only_matching_calendar_days():
    plan = demo_plan()
    request = plan.request.model_copy(update={"start_date": date(2027, 1, 1)})
    payload = payload_from_plan(plan)
    for number, day in enumerate(payload.days, 1):
        day.date = date(2027, 1, number)
    assert build_plan(payload, request, plan.trip_id).days[2].date == date(2027, 1, 3)


def test_destination_order_and_missing_intercity_transfer():
    plan = demo_plan()
    reversed_request = plan.request.model_copy(update={"destinations": list(reversed(plan.request.destinations))})
    with pytest.raises(ValueError, match="original order"):
        build_plan(payload_from_plan(plan), reversed_request, plan.trip_id)
    payload = payload_from_plan(plan)
    payload.days[2].schedule.pop(0)
    with pytest.raises(ValueError, match="intercity transfer"):
        build_plan(payload, plan.request, plan.trip_id)


def test_multi_segment_transfer_chain_must_connect():
    plan = demo_plan()
    payload = payload_from_plan(plan)
    transfer = payload.days[0].schedule[1]
    transfer.end_time = "11:15"
    transfer.duration_minutes = transfer.travel.duration_minutes = 15
    second = transfer.model_copy(deep=True)
    second.start_time, second.end_time = "11:15", "11:30"
    second.travel.origin = "Unrelated station in Paris"
    payload.days[0].schedule.insert(2, second)
    with pytest.raises(ValueError, match="segments must connect"):
        build_plan(payload, plan.request, plan.trip_id)
