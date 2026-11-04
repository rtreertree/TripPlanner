"""Local business rules: request readiness, schedules, identity, and exact sums."""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import BudgetSummary, Day, GenerationMetadata, ItineraryPayload, RequestDraft, SavedPlan, TripRequest

MAX_TRIP_DAYS = 21
COST_CATEGORIES = ("accommodation", "food", "transport", "activities", "other")
BUDGET_SCOPE = (
    "Estimates for the entire group, including accommodation, meals, activities, local transport, "
    "and transfers between requested destinations. Travel from home and back is excluded unless explicitly requested."
)


def normalize_request(draft: RequestDraft) -> TripRequest:
    """Apply documented defaults only after resolving required and material details."""
    destinations = []
    for place in draft.destinations or []:
        place = place.strip()
        if place and place.casefold() not in {entry.casefold() for entry in destinations}:
            destinations.append(place)
    if not destinations:
        raise ValueError("Where would you like to go? For example, Tokyo then Kyoto.")
    if draft.duration_days is None:
        raise ValueError("How many days is your trip? For example, five days.")
    if draft.duration_days < 1:
        raise ValueError("How many days would you like? Please choose at least one day.")
    if draft.duration_days > MAX_TRIP_DAYS:
        raise ValueError(f"This version supports trips of up to {MAX_TRIP_DAYS} days. How many days should I plan?")
    if draft.travelers is not None and draft.travelers < 1:
        raise ValueError("How many people are traveling? Please choose at least one traveler.")
    if draft.budget is not None and draft.budget <= 0:
        raise ValueError("What positive budget should I use, or would you prefer no spending limit?")
    if draft.budget is not None and not draft.currency:
        raise ValueError("Which currency is your budget in? For example, USD, JPY, or THB.")
    if draft.budget_per_person and (draft.travelers is None or draft.travelers_explicit is not True):
        raise ValueError("How many people are traveling? I need this to convert your per-person budget to the group total.")
    currency = (draft.currency or "USD").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Which three-letter currency code should I use? For example, USD, JPY, or THB.")
    travelers = draft.travelers or 1
    budget = draft.budget
    if budget is not None and draft.budget_per_person:
        budget = float(Decimal(str(budget)) * travelers)
    return TripRequest(
        trip_name=(draft.trip_name or "").strip() or f"{' & '.join(destinations)} · {draft.duration_days} days",
        destinations=destinations,
        duration_days=draft.duration_days,
        budget=budget,
        currency=currency,
        preferences=(draft.preferences or "").strip(),
        start_date=draft.start_date,
        travelers=travelers,
        pace=draft.pace or "balanced",
        destination_delegated=draft.destination_delegated or False,
    )


def _matches(first: str, second: str) -> bool:
    clean = lambda value: re.sub(r"[^\w]+", " ", value.casefold()).strip()
    left, right = clean(first), clean(second)
    return bool(left and right and (left == right or left in right or right in left))


def _zone(value: str):
    if re.fullmatch(r"[+-]\d{2}:\d{2}", value):
        hours, minutes = map(int, value[1:].split(":"))
        if hours > 23 or minutes > 59:
            raise ValueError(f"Invalid timezone offset: {value}.")
        return timezone(timedelta(minutes=(hours * 60 + minutes) * (-1 if value[0] == "-" else 1)))
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Use an IANA timezone or explicit UTC offset instead of {value!r}.") from None


def _instant(local_time: str, zone: str, offset: int, base: date) -> datetime:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", local_time):
        raise ValueError(f"Use a 24-hour HH:MM time instead of {local_time!r}.")
    if offset < 0:
        raise ValueError("Schedule day offsets must be zero or positive.")
    hour, minute = map(int, local_time.split(":"))
    return datetime.combine(base + timedelta(days=offset), datetime.min.time()).replace(
        hour=hour, minute=minute, tzinfo=_zone(zone)
    ).astimezone(timezone.utc)


def _cost_amount(cost, currency: str) -> Decimal | None:
    if cost.currency != currency:
        raise ValueError(f"Every cost must use the reporting currency {currency}.")
    if cost.amount is None:
        return None
    if cost.amount < 0:
        raise ValueError("Estimated costs cannot be negative.")
    return Decimal(str(cost.amount))


def _check_days(payload: ItineraryPayload, request: TripRequest) -> None:
    if len(payload.days) != request.duration_days:
        raise ValueError(f"The itinerary must contain exactly {request.duration_days} days.")
    if [day.day_number for day in payload.days] != list(range(1, request.duration_days + 1)):
        raise ValueError("Itinerary days must be numbered consecutively from 1.")
    covered = [place for day in payload.days for place in day.destinations]
    if not request.destination_delegated:
        missing = [place for place in request.destinations if not any(_matches(place, included) for included in covered)]
        if missing:
            raise ValueError(f"The itinerary is missing requested destinations: {', '.join(missing)}. Explain feasibility or include them.")
    previous_end = None
    previous_day = None
    visited_destinations = []
    previous_city = None
    routes_since_visit = []
    for day in payload.days:
        expected_date = request.start_date + timedelta(days=day.day_number - 1) if request.start_date else None
        if day.date != expected_date:
            raise ValueError("Day dates must match the requested start date, or remain null for an undated trip.")
        if not day.title.strip() or not day.summary.strip() or not day.destinations or not day.schedule:
            raise ValueError(f"Day {day.day_number} needs a title, summary, destinations, and a usable schedule.")
        base = expected_date or date(2026, 1, 5) + timedelta(days=day.day_number - 1)
        prior_visit = None
        transfers = []
        for item in day.schedule:
            if not item.title.strip() or item.duration_minutes <= 0:
                raise ValueError("Every schedule item needs a title and a positive duration.")
            start = _instant(item.start_time, item.start_timezone, item.start_day_offset, base)
            end = _instant(item.end_time, item.end_timezone, item.end_day_offset, base)
            if int((end - start).total_seconds()) != item.duration_minutes * 60:
                raise ValueError(f"The times and duration for {item.title!r} are inconsistent.")
            if previous_end is not None and start < previous_end:
                raise ValueError(f"{item.title!r} overlaps an earlier schedule item.")
            previous_end = end
            if item.kind == "travel":
                if item.travel is None:
                    raise ValueError("Every travel item needs route and transport details.")
                if item.travel.duration_minutes <= 0 or item.duration_minutes < item.travel.duration_minutes:
                    raise ValueError("Allow enough scheduled time for the estimated transfer duration.")
                if not all(value.strip() for value in (item.travel.origin, item.travel.destination, item.travel.transport_mode)):
                    raise ValueError("Transfers need an origin, destination, and transport method.")
                transfers.append(item.travel)
                routes_since_visit.append(item.travel)
            elif item.travel is not None:
                raise ValueError("Travel details belong on travel schedule items.")
            if item.kind in ("activity", "meal"):
                if not item.place_name or not item.location:
                    raise ValueError("Visits and meals need a meaningful place name and location.")
                cities = [place for place in request.destinations
                          if any(_matches(place.split(",")[0], value) for value in (item.location, item.place_name))]
                if not request.destination_delegated and cities:
                    city = cities[0]
                    if city not in visited_destinations:
                        visited_destinations.append(city)
                    if previous_city and city != previous_city:
                        if not routes_since_visit or not (
                            _matches(routes_since_visit[0].origin, previous_city.split(",")[0])
                            and _matches(routes_since_visit[-1].destination, city.split(",")[0])
                        ):
                            raise ValueError("A change of destination needs a connecting intercity transfer.")
                    previous_city = city
                for earlier, later in zip(routes_since_visit, routes_since_visit[1:]):
                    if not _matches(earlier.destination, later.origin):
                        raise ValueError("Consecutive transfer segments must connect to each other.")
                routes_since_visit = []
                if prior_visit and not _matches(prior_visit.place_name, item.place_name):
                    if not transfers:
                        raise ValueError(f"Add a transfer between {prior_visit.place_name} and {item.place_name}.")
                    if not any(_matches(transfers[0].origin, value) for value in (prior_visit.place_name, prior_visit.location)):
                        raise ValueError("A transfer origin must connect to the preceding visit.")
                    if not any(_matches(transfers[-1].destination, value) for value in (item.place_name, item.location)):
                        raise ValueError("A transfer destination must connect to the following visit.")
                prior_visit, transfers = item, []
        kinds = {item.kind for item in day.schedule}
        if "meal" not in kinds or not kinds.intersection({"rest", "free_time"}):
            raise ValueError(f"Day {day.day_number} must include meals and time for rest or free time.")
        if previous_day and not any(_matches(a, b) for a in previous_day.destinations for b in day.destinations):
            routes = [item.travel for source in (previous_day, day) for item in source.schedule if item.travel]
            if not any(any(_matches(route.origin, place) for place in previous_day.destinations)
                       and any(_matches(route.destination, place) for place in day.destinations) for route in routes):
                raise ValueError("A change of destination needs an explicit intercity transfer with scheduled travel time.")
        previous_day = day
    if not request.destination_delegated and visited_destinations != request.destinations:
        if set(visited_destinations) == set(request.destinations):
            raise ValueError("Visit requested destinations in their original order unless the user asks to optimize it.")
        raise ValueError("Each requested destination needs an actual visit with a meaningful location in its schedule.")


def build_plan(payload: ItineraryPayload, request: TripRequest, trip_id: str,
               previous: SavedPlan | None = None, generation: GenerationMetadata | None = None,
               restored_from: SavedPlan | None = None) -> SavedPlan:
    """Validate a candidate before assigning app-owned identifiers and totals."""
    request = normalize_request(RequestDraft(**request.model_dump(), travelers_explicit=True))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", trip_id):
        raise ValueError("Trip IDs must be safe application-generated identifiers.")
    if previous and previous.trip_id != trip_id:
        raise ValueError("A revision must preserve the trip identity.")
    _check_days(payload, request)
    old_items = {item.id: item for day in previous.days for item in day.schedule} if previous else {}
    if restored_from:
        if restored_from.trip_id != trip_id:
            raise ValueError("Undo must restore a revision of the same trip.")
        old_items.update({item.id: item for day in restored_from.days for item in day.schedule})
    used_ids = set()
    categories = {category: Decimal("0") for category in COST_CATEGORIES}
    partial = False
    days = []
    for day in payload.days:
        total = Decimal("0")
        schedule = []
        for item in day.schedule:
            # An AI may refer to an existing item, but cannot invent application IDs.
            item_id = item.id if item.id in old_items else None
            if item_id is None and previous:
                match = next((old.id for old in old_items.values() if old.kind == item.kind
                              and old.title == item.title and old.place_name == item.place_name
                              and old.id not in used_ids), None)
                item_id = match
            item_id = item_id or str(uuid4())
            if item_id in used_ids:
                raise ValueError("Schedule item IDs must be unique.")
            used_ids.add(item_id)
            schedule.append(item.model_copy(update={"id": item_id}))
        for cost in [item.cost for item in schedule] + day.additional_costs:
            amount = _cost_amount(cost, request.currency)
            if amount is None:
                partial = True
            else:
                total += amount
                categories[cost.category] += amount
        days.append(Day(**day.model_dump(exclude={"schedule"}), schedule=schedule, estimated_total_cost=float(total)))
    estimated_total = sum(categories.values(), Decimal("0"))
    remaining = Decimal(str(request.budget)) - estimated_total if request.budget is not None else None
    status = "uncertain" if partial else "no_limit" if remaining is None else "over_budget" if remaining < 0 else "within_budget"
    warnings = list(payload.warnings)
    if partial:
        warnings.append("Some costs are unknown. Totals are partial estimates and budget status is uncertain.")
    elif remaining is not None and remaining < 0:
        warnings.append(f"Estimated group cost exceeds the budget by {float(-remaining):,.2f} {request.currency}. Consider cheaper accommodation or fewer paid activities.")
    now = datetime.now(timezone.utc).isoformat()
    metadata = generation or GenerationMetadata()
    if not metadata.generated_at:
        metadata = metadata.model_copy(update={"generated_at": now})
    assumptions = list(payload.assumptions)
    if not request.start_date:
        assumptions.append("Numbered days have no calendar dates; timezone calculations use a representative date. Confirm seasonal clock changes before travel.")
    return SavedPlan(
        trip_id=trip_id, revision=previous.revision + 1 if previous else 1,
        created_at=previous.created_at if previous else now, updated_at=now,
        request=request, summary=payload.summary, days=days,
        budget_summary=BudgetSummary(scope=BUDGET_SCOPE, category_totals={key: float(value) for key, value in categories.items()},
                                     estimated_total=float(estimated_total), budget_limit=request.budget,
                                     remaining=float(remaining) if remaining is not None else None,
                                     currency=request.currency, status=status, partial=partial),
        assumptions=list(dict.fromkeys(assumptions)), warnings=list(dict.fromkeys(warnings)), generation=metadata,
    )


def validate_plan(plan: SavedPlan) -> SavedPlan:
    """Verify persisted arithmetic and domain rules without replacing IDs or metadata."""
    if plan.schema_version != "1.0" or plan.revision < 1:
        raise ValueError("Unsupported plan schema or invalid revision.")
    for stamp in (plan.created_at, plan.updated_at, plan.generation.generated_at):
        try:
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if parsed.utcoffset() != timedelta(0):
                raise ValueError
        except ValueError:
            raise ValueError("Plan timestamps must be valid UTC timestamps.") from None
    ids = [item.id for day in plan.days for item in day.schedule]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Saved schedule items require unique stable IDs.")
    candidate = build_plan(ItineraryPayload(summary=plan.summary, days=[day.model_dump(exclude={"estimated_total_cost"}) for day in plan.days],
                                           assumptions=plan.assumptions, warnings=plan.warnings),
                           plan.request, plan.trip_id, generation=plan.generation)
    if candidate.budget_summary != plan.budget_summary or any(a.estimated_total_cost != b.estimated_total_cost for a, b in zip(candidate.days, plan.days)):
        raise ValueError("Saved cost totals do not match itemized expenses.")
    return plan


def payload_from_plan(plan: SavedPlan) -> ItineraryPayload:
    """Extract only planner-owned fields, retaining references to surviving items."""
    return ItineraryPayload(summary=plan.summary,
                            days=[day.model_dump(exclude={"estimated_total_cost"}) for day in plan.days],
                            assumptions=plan.assumptions, warnings=plan.warnings)
